"""Page-change hardening (2026-10-08): the bot must notice when OpenRent changes
a page, and never act wrongly on a page it can no longer read.

Covers: own-message detection on threads (a renamed `current-user` class would
make every thread look like the landlord spoke last and trigger a reply to our
own message on every run), reply send confirmation, the early-access enquiry
wall, the fleet-wide failure-spike evaluation and the pause breakers."""
import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.alerts import health_checks as hc
from app.db import repository
from app.db.models import Base
from app.openrent import inbox, messaging
from app.services import page_health


# ---- fakes -----------------------------------------------------------------

class FakeMsg:
    def __init__(self, text, ours, ts="1759900000"):
        self.text = text
        self.classes = "message-content current-user" if ours else "message-content"
        self.ts = ts

    async def inner_text(self):
        return self.text

    async def get_attribute(self, name):
        return self.classes if name == "class" else self.ts


class FakeThreadPage:
    def __init__(self, msgs, url="https://www.openrent.co.uk/messages/46000001"):
        self.msgs = msgs
        self.url = url

    async def query_selector_all(self, selector):
        return self.msgs


@pytest.fixture()
def steps(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        page_health, "record_step",
        lambda step, ok, detail=None, account_id=None: recorded.append((step, ok)),
    )

    async def no_popup(page):
        return None

    monkeypatch.setattr(inbox, "close_verified_tenant_popup", no_popup)
    return recorded


def _outbound(monkeypatch, texts):
    monkeypatch.setattr(repository, "get_outbound_message_texts", lambda thread_id: texts)


# ---- own-message detection ----------------------------------------------------

def test_thread_with_no_marked_message_of_ours_is_refused(monkeypatch, steps):
    _outbound(monkeypatch, [])
    page = FakeThreadPage([
        FakeMsg("Hi, is the flat still available? We are a couple...", ours=False),
        FakeMsg("Yes it is, when would you like to view?", ours=False),
    ])
    with pytest.raises(inbox.SenderDetectionError):
        asyncio.run(inbox.extract_conversation(page))
    assert steps == [(page_health.THREAD_READ, False)]


def test_unmarked_message_matching_what_we_sent_is_ours(monkeypatch, steps):
    sent = "Hi there, could we come and see it on Saturday around 11am? - Thanks, Ella"
    _outbound(monkeypatch, ["Hello, is the 2 bed still available? We'd love to view it.", sent])
    page = FakeThreadPage([
        FakeMsg("Hello, is the 2 bed still available? We'd love to view it.", ours=True),
        FakeMsg("Yes, still available.", ours=False),
        # OpenRent showed our reply without the marker, and with the dash gone.
        FakeMsg("Hi there, could we come and see it on Saturday around 11am?  Thanks, Ella", ours=False),
    ])
    messages = asyncio.run(inbox.extract_conversation(page))
    assert [m["sender"] for m in messages] == ["us", "landlord", "us"]
    assert inbox.should_ai_reply(messages) is False
    assert steps == [(page_health.THREAD_READ, True)]


def test_redacted_number_and_short_texts_in_matching():
    keys = [inbox._match_key("My partner's WhatsApp is 07783 129181, they handle viewings")]
    assert inbox.is_our_stored_message(
        "My partner's WhatsApp is (Number Removed), they handle viewings", keys
    )
    # Too short to tell apart from a landlord's own "ok thanks".
    assert not inbox.is_our_stored_message("ok thanks", [inbox._match_key("ok thanks")])


def test_landlord_message_stays_landlord(monkeypatch, steps):
    _outbound(monkeypatch, ["Hello, is the 2 bed still available? We'd love to view it."])
    page = FakeThreadPage([
        FakeMsg("Hello, is the 2 bed still available? We'd love to view it.", ours=True),
        FakeMsg("Can you do Tuesday at 6pm for a viewing of the property?", ours=False),
    ])
    messages = asyncio.run(inbox.extract_conversation(page))
    assert messages[-1]["sender"] == "landlord"
    assert inbox.should_ai_reply(messages) is True


# ---- reply send confirmation ------------------------------------------------

class FakeLocator:
    def __init__(self, page):
        self.page = page

    async def count(self):
        return len(self.page.own)

    def nth(self, i):
        page = self.page

        class _El:
            async def inner_text(self_inner):
                return page.own[i]

        return _El()


class FakeSendPage:
    def __init__(self, own, after_click_own, box_after):
        self.own = own
        self.after_click_own = after_click_own
        self.box_after = box_after
        self.url = "https://www.openrent.co.uk/messages/46000002"

    def locator(self, selector):
        return FakeLocator(self)

    async def wait_for_timeout(self, ms):
        self.own = self.after_click_own


class FakeBox:
    def __init__(self, page):
        self.page = page

    async def input_value(self, timeout=None):
        return self.page.box_after


def test_reply_confirmed_when_our_new_message_appears():
    page = FakeSendPage(["first"], ["first", "Sounds great, see you then"], box_after="")
    ok, in_box = asyncio.run(
        inbox._confirm_reply_sent(page, FakeBox(page), "Sounds great, see you then", 1, timeout_ms=2000)
    )
    assert (ok, in_box) == (True, False)


def test_reply_not_sent_when_text_still_in_box():
    reply = "Sounds great, see you on Saturday at eleven"
    page = FakeSendPage(["first"], ["first"], box_after=reply)
    ok, in_box = asyncio.run(
        inbox._confirm_reply_sent(page, FakeBox(page), reply, 1, timeout_ms=2000)
    )
    assert (ok, in_box) == (False, True)


# ---- early access -----------------------------------------------------------

class FakeEarlyAccessPage:
    url = "https://www.openrent.co.uk/messagelandlord/3066823"

    async def goto(self, *a, **k):
        return None

    async def content(self):
        return (
            "<h1>You've selected an early access property.</h1>"
            "<p>Enquiries are restricted to Verified Tenants.</p>"
        )


def test_early_access_page_raises_distinct_error(monkeypatch):
    recorded = []
    monkeypatch.setattr(page_health, "record_step", lambda *a, **k: recorded.append(a))
    with pytest.raises(messaging.EarlyAccessRestricted):
        asyncio.run(
            messaging.send_initial_message(
                FakeEarlyAccessPage(), FakeEarlyAccessPage.url, "hello", {}
            )
        )
    assert recorded == []   # not a page fault: no health failure


def test_early_access_listing_is_tagged_not_failed(monkeypatch):
    from scripts import process_listings as pl

    class Acc:
        id = 43
        email = "h@x"

    class L:
        id = 7
        property_url = "https://www.openrent.co.uk/3066823"
        listing_id = "3066823"

    tagged, failed = [], []

    async def anon(*a, **k):
        return None

    async def not_agent(*a, **k):
        return False

    async def link(page):
        return "/messagelandlord/3066823"

    async def meta(page):
        return {"rent_pcm": 1500, "bedrooms": 1}

    async def blocked(**k):
        raise messaging.EarlyAccessRestricted("x", 720)

    monkeypatch.setattr(pl, "account_stop_requested", lambda _id: False)
    monkeypatch.setattr(pl, "open_listing", anon)
    monkeypatch.setattr(pl, "get_existing_thread_id", anon)
    monkeypatch.setattr(pl, "random_sleep", anon)
    monkeypatch.setattr(pl, "landlord_is_agent", not_agent)
    monkeypatch.setattr(pl, "landlord_already_contacted", lambda _pk: False)
    monkeypatch.setattr(pl, "extract_listing_metadata", meta)
    monkeypatch.setattr(pl, "save_listing_metadata", lambda *a: None)
    monkeypatch.setattr(pl, "get_message_link", link)
    monkeypatch.setattr(pl, "can_send_message", lambda _id: True)
    monkeypatch.setattr(pl, "save_message_url", lambda *a: None)
    monkeypatch.setattr(pl, "generate_initial_property_message", lambda *a, **k: ("hi", None))
    monkeypatch.setattr(pl, "send_initial_message", blocked)
    monkeypatch.setattr(
        pl, "mark_listing_early_access", lambda pk, acc, unlock=None: tagged.append((pk, acc, unlock))
    )
    monkeypatch.setattr(pl, "mark_listing_failed", lambda *a, **k: failed.append(a))
    monkeypatch.setattr(pl, "release_listing_claim", lambda *a: None)

    result = asyncio.run(pl._process_claimed_listings(Acc(), None, [L()], {}, "w-43", {}))

    assert tagged == [(7, 43, 720)]
    assert failed == []
    assert result == (0, 0, 1, 0)


# ---- fleet failure spikes ---------------------------------------------------

def test_one_account_failing_is_not_a_page_change():
    rows = [("enquiry_form", 27, False, "#Availability not visible")] * 9
    rows += [("enquiry_form", acc, True, None) for acc in (22, 23, 24)]
    assert hc.evaluate_step_health(rows)["enquiry_form"]["status"] == "quiet"


def test_several_accounts_failing_is_a_page_change():
    rows = [("enquiry_form", acc, False, "#Availability not visible") for acc in (22, 23, 24, 26, 34)]
    rows += [("enquiry_form", 40, True, None)]
    s = hc.evaluate_step_health(rows)["enquiry_form"]
    assert s["status"] == "failing"
    assert s["fail_accounts"] == {22, 23, 24, 26, 34}


def test_step_recovers_on_successes():
    rows = [("reply_send", acc, True, None) for acc in (22, 23, 24, 26)]
    rows += [("reply_send", 27, False, "x")]
    assert hc.evaluate_step_health(rows)["reply_send"]["status"] == "recovered"


def test_login_alert_only_for_accounts_with_no_success():
    rows = [(36, False, "Email field not found")] * 3 + [(22, False, "t"), (22, True, None)] * 2
    assert hc.failing_login_accounts(rows) == {36: (3, "Email field not found")}


# ---- breakers ---------------------------------------------------------------

@pytest.fixture()
def settings_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'ph.db'}")
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", Session)
    return Session


def test_breaker_trips_expires_and_manual_resume_is_stamped(settings_db):
    assert not page_health.is_paused(page_health.OUTREACH)
    page_health.trip_breaker(page_health.OUTREACH, 90, "enquiry_form failing 6/7")
    assert page_health.is_paused(page_health.OUTREACH)
    assert page_health.breaker_state(page_health.OUTREACH)["reason"] == "enquiry_form failing 6/7"
    assert not page_health.is_paused(page_health.REPLIES)

    assert page_health.clear_breaker(page_health.OUTREACH, manual=True) is True
    assert not page_health.is_paused(page_health.OUTREACH)
    assert page_health.resumed_at(page_health.OUTREACH) > datetime.utcnow() - timedelta(minutes=1)

    page_health.trip_breaker(page_health.REPLIES, 0, "expired")
    assert not page_health.is_paused(page_health.REPLIES)


def test_record_step_writes_row_with_current_account(settings_db):
    from app.db.models import StepHealthEvent

    page_health.set_current_account(42)
    page_health.record_step(page_health.INBOX, False, "no thread cards")
    page_health.set_current_account(None)
    with settings_db() as s:
        row = s.query(StepHealthEvent).one()
        assert (row.step, row.account_id, row.ok, row.detail) == ("inbox", 42, False, "no thread cards")


def test_paused_replies_never_type(monkeypatch):
    monkeypatch.setattr(page_health, "is_paused", lambda scope: scope == page_health.REPLIES)

    class Boom:
        url = "https://www.openrent.co.uk/messages/1"

        def locator(self, _):
            raise AssertionError("must not touch the page while replies are paused")

    assert asyncio.run(inbox.send_reply(Boom(), "hello")) is False
