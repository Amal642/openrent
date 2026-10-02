"""Multiple WhatsApp numbers ("lines"), Kapso exit phase 2.

- a contact remembers which of our numbers it last wrote to
- replies go out from that number (Meta); unknown lines fall back to the default
- with Kapso (single project number) the line is ignored
- handoff priors only count for the number the landlord actually wrote to
- with no line info everything behaves exactly like the single-number setup
"""
import asyncio
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import whatsapp_router
from app.db import repository as db_repository
from app.db.models import Base, Conversation, Listing, WhatsAppHandoffIntent
from app.whatsapp import handler, kapso_worker, lines, matcher, repository
from app.whatsapp.kapso_worker import KapsoWhatsAppWorker

LINE_A = "1334185119782926"   # +44 7783 129181
LINE_B = "2222222222222222"   # second number
NUM_A = "07783129181"
NUM_B = "07700900222"


@pytest.fixture()
def wa_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'wa.db'}")
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_repository, "SessionLocal", Session)
    monkeypatch.setattr(repository, "SessionLocal", Session)
    monkeypatch.setattr(matcher, "SessionLocal", Session)
    monkeypatch.setattr(handler.settings, "WHATSAPP_AUTO_REPLY_ENABLED", False)
    monkeypatch.setattr(handler, "generate_closing_reply", lambda name=None: "Thanks")
    return Session


@pytest.fixture()
def two_lines(monkeypatch):
    monkeypatch.setattr(lines.settings, "META_WA_PHONE_NUMBER_ID", LINE_A)
    monkeypatch.setattr(lines.settings, "META_WA_PHONE_NUMBER_IDS", LINE_B)


def _seed(session, *, name, address, listing_id, thread_id):
    listing = Listing(
        listing_id=listing_id,
        property_url=f"https://example.com/{listing_id}",
        landlord_name=name,
        property_address=address,
        thread_id=thread_id,
        message_sent=True,
    )
    session.add(listing)
    session.flush()
    session.add(Conversation(thread_id=thread_id, listing_id=listing.id))
    session.commit()
    return listing.id


# ── Number helpers ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["07783129181", "+44 7783 129181", "447783129181", "07783 129181"])
def test_national_digits_normalises_uk_formats(raw):
    assert lines.national_digits(raw) == "7783129181"


def test_national_digits_empty():
    assert lines.national_digits(None) == ""


def test_accepted_ids_include_default_and_extras(two_lines):
    assert lines.accepted_phone_number_ids() == {LINE_A, LINE_B}


def test_send_line_uses_contact_line_or_falls_back(two_lines):
    assert lines.meta_send_phone_number_id(LINE_B) == LINE_B
    assert lines.meta_send_phone_number_id(None) == LINE_A
    assert lines.meta_send_phone_number_id("9999-retired") == LINE_A


def test_single_number_setup_unchanged(monkeypatch):
    monkeypatch.setattr(lines.settings, "META_WA_PHONE_NUMBER_ID", LINE_A)
    monkeypatch.setattr(lines.settings, "META_WA_PHONE_NUMBER_IDS", "")
    assert lines.accepted_phone_number_ids() == {LINE_A}
    assert lines.meta_send_phone_number_id(LINE_B) == LINE_A


# ── Contact remembers its line ───────────────────────────────────────────────

def _capture(phone, msg_id, line):
    return repository.capture_incoming_message(
        phone=phone,
        message="hello",
        received_at=datetime.utcnow(),
        message_id=msg_id,
        line_phone_number_id=line,
    )


def test_contact_records_and_switches_line(wa_db):
    c = _capture("447911000001", "m1", LINE_A)
    assert c.line_phone_number_id == LINE_A
    c = _capture("447911000001", "m2", LINE_B)
    assert c.line_phone_number_id == LINE_B


def test_message_without_line_keeps_existing_line(wa_db):
    _capture("447911000002", "m1", LINE_B)
    c = _capture("447911000002", "m2", None)
    assert c.line_phone_number_id == LINE_B


def test_handler_passes_line_to_capture(wa_db, monkeypatch):
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: None)
    monkeypatch.setattr(handler, "extract_property_from_message", lambda text: None)
    asyncio.run(handler.handle_incoming_message(
        phone_number="447911000003", message="Hi", message_id="m1",
        line_phone_number_id=LINE_B, line_display_number="447700900222",
    ))
    assert repository.get_contact_by_phone("447911000003").line_phone_number_id == LINE_B


# ── Sending from the right line ──────────────────────────────────────────────

def _fake_http(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

    class FakeClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            return FakeResponse()

    async def no_publish(self):
        return None

    monkeypatch.setattr("app.whatsapp.kapso_worker.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(KapsoWhatsAppWorker, "_publish_status", no_publish)
    return captured


def _meta(monkeypatch):
    s = kapso_worker.settings
    monkeypatch.setattr(s, "WHATSAPP_PROVIDER", "meta")
    monkeypatch.setattr(s, "META_GRAPH_BASE_URL", "https://graph.facebook.com/v24.0")
    monkeypatch.setattr(s, "META_WA_ACCESS_TOKEN", "tok")


def _send(phone, line=None):
    worker = KapsoWhatsAppWorker()
    worker.status = "connected"
    return asyncio.run(worker.send_message(phone, "Hi", line))


def test_meta_send_uses_explicit_line(monkeypatch, two_lines):
    captured = _fake_http(monkeypatch)
    _meta(monkeypatch)
    assert _send("447911000004", LINE_B)
    assert captured["url"].endswith(f"/{LINE_B}/messages")


def test_meta_send_looks_up_contact_line_when_not_given(monkeypatch, two_lines):
    captured = _fake_http(monkeypatch)
    _meta(monkeypatch)
    monkeypatch.setattr(kapso_worker, "_contact_line", lambda phone: LINE_B)
    assert _send("447911000005")
    assert captured["url"].endswith(f"/{LINE_B}/messages")


def test_meta_send_unknown_contact_uses_default(monkeypatch, two_lines):
    captured = _fake_http(monkeypatch)
    _meta(monkeypatch)
    monkeypatch.setattr(kapso_worker, "_contact_line", lambda phone: None)
    assert _send("447911000006")
    assert captured["url"].endswith(f"/{LINE_A}/messages")


def test_kapso_ignores_line(monkeypatch, two_lines):
    captured = _fake_http(monkeypatch)
    s = kapso_worker.settings
    monkeypatch.setattr(s, "WHATSAPP_PROVIDER", "kapso")
    monkeypatch.setattr(s, "KAPSO_BASE_URL", "https://api.kapso.ai/meta/whatsapp/v24.0")
    monkeypatch.setattr(s, "KAPSO_API_KEY", "k")
    monkeypatch.setattr(s, "KAPSO_PHONE_NUMBER_ID", "kpnid")

    def boom(phone):
        raise AssertionError("Kapso must not look up lines")

    monkeypatch.setattr(kapso_worker, "_contact_line", boom)
    assert _send("447911000007", LINE_B)
    assert captured["url"].endswith("/kpnid/messages")
    assert _send("447911000007")


# ── Handoff prior scoped to the number written to ────────────────────────────

def _two_nicolas(session):
    a = _seed(session, name="Nicola A.", address="10 Oak Road, SE1", listing_id="L-A", thread_id="T-A")
    b = _seed(session, name="Nicola B.", address="20 Pine Road, N1", listing_id="L-B", thread_id="T-B")
    return a, b


def test_line_scopes_handoff_to_the_number_shared(wa_db):
    with wa_db() as session:
        a, b = _two_nicolas(session)
    repository.record_handoff_intent("T-A", shared_number=NUM_A)
    repository.record_handoff_intent("T-B", shared_number=NUM_B)

    # Unknown line: both handoffs count -> ambiguous, stays unmatched.
    candidates, confidence = matcher.match_by_evidence(["Nicola"], [])
    assert handler._match_status(candidates, confidence) == "UNMATCHED"

    # Wrote to number B: only the B handoff counts -> resolves.
    candidates, confidence = matcher.match_by_evidence(["Nicola"], [], line_number="447700900222")
    assert candidates[0]["listing_id"] == b
    assert handler._match_status(candidates, confidence) == "MATCHED"


def test_legacy_intents_without_number_still_count(wa_db):
    with wa_db() as session:
        a, _ = _two_nicolas(session)
    repository.record_handoff_intent("T-A")  # recorded before multi-number
    candidates, _ = matcher.match_by_evidence(["Nicola"], [], line_number="447700900222")
    assert any(c["listing_id"] == a and c["reason"] == "handoff" for c in candidates)


def test_reused_intent_gets_shared_number_backfilled(wa_db):
    with wa_db() as session:
        _two_nicolas(session)
    first = repository.record_handoff_intent("T-A")
    again = repository.record_handoff_intent("T-A", shared_number=NUM_A)
    assert again.id == first.id
    with wa_db() as session:
        assert session.get(WhatsAppHandoffIntent, first.id).shared_number == NUM_A


# ── Kapso inbound carries the line too ───────────────────────────────────────

def test_kapso_v2_extract_includes_line():
    payload = {
        "message": {"id": "wamid.1", "type": "text", "from": "447911123456",
                    "text": {"body": "hi"}, "kapso": {"direction": "inbound"}},
        "conversation": {"phone_number": "447911123456", "phone_number_id": LINE_A},
        "phone_number_id": LINE_A,
    }
    [m] = whatsapp_router._extract_incoming_messages(payload)
    assert m["line_phone_number_id"] == LINE_A
