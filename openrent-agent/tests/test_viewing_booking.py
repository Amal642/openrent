import asyncio
import contextlib
from types import SimpleNamespace

from app.openrent import viewing_booking


class FakeLocator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    @property
    def first(self):
        return self

    async def count(self):
        return 1 if self.selector in self.page.present() else 0

    async def get_attribute(self, name):
        return "/enquiries/cancelviewing?rentalListingID=1&enquiryID=2&mobile=%2B44"

    async def fill(self, value):
        self.page.filled = value

    async def click(self):
        self.page.clicked = self.selector
        self.page.submitted = True


class FakePage:
    """Thread page with a booking; the cancel form page; the thread after submit."""

    def __init__(self, booked=True, form=True, withdrawn_on_submit=True):
        self.booked, self.form, self.withdrawn_on_submit = booked, form, withdrawn_on_submit
        self.where = "thread"
        self.url = "https://www.openrent.co.uk/messages/1"
        self.filled = self.clicked = None
        self.submitted = False
        self.gotos = []

    def present(self):
        if self.where == "form":
            return {viewing_booking.REASON_BOX, viewing_booking.CANCEL_BUTTON} if self.form else set()
        still_booked = self.booked and not (self.submitted and self.withdrawn_on_submit)
        return {viewing_booking.CANCEL_LINK} if still_booked else set()

    def locator(self, selector):
        return FakeLocator(self, selector)

    async def goto(self, url, **_):
        self.gotos.append(url)
        self.where = "form"
        self.url = url

    @contextlib.asynccontextmanager
    async def expect_navigation(self, **_):
        yield
        self.where = "result"


def _patch(monkeypatch, recorded):
    async def open_thread(page, thread_id):
        page.where = "thread"

    async def noop(*_a, **_k):
        return None

    monkeypatch.setattr(viewing_booking, "open_thread", open_thread)
    monkeypatch.setattr(viewing_booking, "close_verified_tenant_popup", noop)
    monkeypatch.setattr(viewing_booking, "random_sleep", noop)
    monkeypatch.setattr(
        viewing_booking, "record_booking_cancel_result",
        lambda thread_id, result: recorded.append((thread_id, result)),
    )


def test_booked_viewing_is_withdrawn_through_the_form(monkeypatch):
    recorded = []
    _patch(monkeypatch, recorded)
    page = FakePage()

    result = asyncio.run(viewing_booking.cancel_openrent_booking(page, "46865576"))

    assert result == "cancelled"
    assert page.gotos == [
        "https://www.openrent.co.uk/enquiries/cancelviewing?rentalListingID=1&enquiryID=2&mobile=%2B44"
    ]
    assert page.filled == viewing_booking.cancellation_reason("46865576")
    assert page.clicked == viewing_booking.CANCEL_BUTTON  # never the "rearrange" button
    assert page.where == "thread"
    assert recorded == [("46865576", "cancelled")]


def test_chat_only_viewing_has_no_booking_to_withdraw(monkeypatch):
    recorded = []
    _patch(monkeypatch, recorded)
    page = FakePage(booked=False)

    assert asyncio.run(viewing_booking.cancel_openrent_booking(page, "t1")) == "no_booking"
    assert page.gotos == [] and not page.submitted
    assert recorded == [("t1", "no_booking")]


def test_booking_still_live_after_submit_is_a_failure(monkeypatch):
    recorded = []
    _patch(monkeypatch, recorded)
    page = FakePage(withdrawn_on_submit=False)

    assert asyncio.run(viewing_booking.cancel_openrent_booking(page, "t2")) == "failed:still_booked"
    assert recorded == [("t2", "failed:still_booked")]


def test_missing_form_does_not_submit(monkeypatch):
    recorded = []
    _patch(monkeypatch, recorded)
    page = FakePage(form=False)

    assert asyncio.run(viewing_booking.cancel_openrent_booking(page, "t3")) == "failed:no_form"
    assert not page.submitted and page.where == "thread"


def test_errors_are_swallowed_and_recorded(monkeypatch):
    recorded = []
    _patch(monkeypatch, recorded)
    page = FakePage()

    async def boom(*_a, **_k):
        raise RuntimeError("navigation timeout")

    page.goto = boom
    result = asyncio.run(viewing_booking.cancel_openrent_booking(page, "t4"))

    assert result == "failed:RuntimeError"
    assert recorded == [("t4", "failed:RuntimeError")]


def test_disabled_by_env_does_nothing(monkeypatch):
    recorded = []
    _patch(monkeypatch, recorded)
    monkeypatch.setenv("OPENRENT_BOOKING_CANCEL", "0")
    page = FakePage()

    assert asyncio.run(viewing_booking.cancel_openrent_booking(page, "t5")) == "disabled"
    assert page.gotos == [] and recorded == []


def test_leftover_sweep_claims_and_releases_each_thread(monkeypatch):
    recorded, claims, releases, cancelled = [], [], [], []
    _patch(monkeypatch, recorded)
    monkeypatch.setattr(viewing_booking, "get_booking_withdrawal_candidates", lambda _id: ["a", "b"])
    monkeypatch.setattr(
        viewing_booking, "claim_conversation",
        lambda t, owner: claims.append(t) or t == "a",
    )
    monkeypatch.setattr(viewing_booking, "release_conversation_claim", lambda t, owner: releases.append(t))

    async def cancel(page, thread_id):
        cancelled.append(thread_id)
        return "cancelled"

    monkeypatch.setattr(viewing_booking, "cancel_openrent_booking", cancel)

    asyncio.run(viewing_booking.withdraw_leftover_bookings(SimpleNamespace(id=24), FakePage(), "w"))

    assert claims == ["a", "b"]
    assert cancelled == ["a"]  # "b" was claimed by another worker
    assert releases == ["a"]


def test_reason_is_stable_per_thread_and_has_no_dashes():
    assert viewing_booking.cancellation_reason("x") == viewing_booking.cancellation_reason("x")
    for reason in viewing_booking._REASONS:
        assert "-" not in reason and "—" not in reason and "–" not in reason
