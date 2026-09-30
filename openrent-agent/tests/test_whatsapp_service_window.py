"""WhatsApp 24h customer-service window in the Kapso dispatch loop.

Outside the window Meta rejects free-text sends, so replies are dropped and
cancellations are skipped BEFORE the AI call (no endless retry + LLM spend).
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import app.whatsapp.repository as wrepo
import app.db.repository as drepo
from app.whatsapp import kapso_worker
from app.whatsapp.kapso_worker import KapsoWhatsAppWorker, service_window_open


def _contact(hours_ago, **kw):
    return SimpleNamespace(
        id=kw.get("id", 1),
        phone_number="447911123456",
        status="AWAITING_PROPERTY",
        last_ai_reply=kw.get("reply", "Which property was it about?"),
        last_received_at=None if hours_ago is None else datetime.utcnow() - timedelta(hours=hours_ago),
    )


def test_window_open_and_closed():
    assert service_window_open(_contact(1))
    assert service_window_open(_contact(23.5))
    assert not service_window_open(_contact(24.5))
    assert not service_window_open(_contact(None))


def _patch_reply_repo(monkeypatch, contact, marked):
    monkeypatch.setattr(wrepo, "get_due_contacts", lambda: [contact])
    monkeypatch.setattr(wrepo, "outbound_message_count", lambda cid: 0)
    monkeypatch.setattr(wrepo, "outbound_message_exists", lambda cid, r: False)
    monkeypatch.setattr(wrepo, "last_message_direction", lambda c: "inbound")
    monkeypatch.setattr(wrepo, "mark_reply_sent", lambda cid: marked.append(cid))
    monkeypatch.setattr(wrepo, "append_outbound_message", lambda cid, r: None)
    monkeypatch.setattr(wrepo, "update_contact", lambda cid, **kw: None)


def test_reply_dropped_when_window_closed(monkeypatch):
    sent, marked = [], []
    _patch_reply_repo(monkeypatch, _contact(30), marked)
    worker = KapsoWhatsAppWorker()

    async def fake_send(phone, text):
        sent.append(text)
        return True

    worker.send_message = fake_send
    asyncio.run(worker._dispatch_due_replies())
    assert sent == []
    assert marked == [1], "stale reply must be cleared so it is not retried forever"


def test_reply_sent_when_window_open(monkeypatch):
    sent, marked = [], []
    _patch_reply_repo(monkeypatch, _contact(2), marked)
    worker = KapsoWhatsAppWorker()

    async def fake_send(phone, text):
        sent.append(text)
        return True

    worker.send_message = fake_send
    asyncio.run(worker._dispatch_due_replies())
    assert sent == ["Which property was it about?"]


def test_cancellation_skipped_before_ai_call_when_window_closed(monkeypatch):
    ai_calls = []
    contact = _contact(48)
    monkeypatch.setattr(wrepo, "get_contacts_due_for_cancellation", lambda: [contact])
    monkeypatch.setattr(wrepo, "get_conversation_for_contact", lambda c: None)
    monkeypatch.setattr(wrepo, "get_contact_messages_for_ai", lambda c: [])
    import app.ai.replies as replies
    monkeypatch.setattr(
        replies, "generate_cancellation_message",
        lambda h: ai_calls.append(1) or ("cancel", None),
    )
    worker = KapsoWhatsAppWorker()

    async def fake_send(phone, text):
        raise AssertionError("must not send outside the window")

    worker.send_message = fake_send
    asyncio.run(worker._dispatch_due_cancellations())
    asyncio.run(worker._dispatch_due_cancellations())
    assert ai_calls == [], "no AI call for a message that cannot be delivered"
    assert contact.id in worker._window_closed_logged
