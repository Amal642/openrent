"""Kapso v2 webhook parsing (payload shape from docs.kapso.ai message-events).

- event name comes from the X-Webhook-Event header
- sender name is conversation.contact_name
- media messages without text must still capture the sender (the lead)
- echoed outbound messages are never treated as landlord messages
- a missing webhook secret rejects (fail closed)
"""
import asyncio
import hashlib
import hmac
import json

from app.api import whatsapp_router


def _v2(msg=None, contact_name="John Doe", phone="447911123456"):
    return {
        "message": msg
        or {
            "id": "wamid.123",
            "timestamp": "1730092800",
            "type": "text",
            "from": phone,
            "text": {"body": "Hi, it's about the flat on Elm Road"},
            "kapso": {"direction": "inbound", "status": "received", "content": "Hi, it's about the flat on Elm Road"},
        },
        "conversation": {
            "id": "conv_123",
            "contact_name": contact_name,
            "phone_number": phone,
            "phone_number_id": "1334185119782926",
        },
        "is_new_conversation": True,
        "phone_number_id": "1334185119782926",
    }


def test_v2_text_message_parsed_with_contact_name():
    [m] = whatsapp_router._extract_incoming_messages(_v2())
    assert m["phone_number"] == "447911123456"
    assert m["message"] == "Hi, it's about the flat on Elm Road"
    assert m["sender_name"] == "John Doe"
    assert m["message_id"] == "wamid.123"


def test_v2_voice_note_keeps_sender_with_transcript():
    msg = {
        "id": "wamid.9",
        "timestamp": "1730092800",
        "type": "audio",
        "from": "447911123456",
        "kapso": {"direction": "inbound", "content": "hi call me about the flat", "has_media": True},
    }
    [m] = whatsapp_router._extract_incoming_messages(_v2(msg))
    assert m["phone_number"] == "447911123456"
    assert m["message"] == "hi call me about the flat"


def test_v2_image_without_caption_uses_placeholder():
    msg = {"id": "wamid.10", "type": "image", "from": "447911123456", "kapso": {"direction": "inbound"}}
    [m] = whatsapp_router._extract_incoming_messages(_v2(msg))
    assert m["phone_number"] == "447911123456"
    assert m["message"] == "[image message]"


def test_v2_phone_falls_back_to_conversation_phone():
    msg = {"id": "wamid.11", "type": "text", "text": {"body": "hello"}, "kapso": {"direction": "inbound"}}
    [m] = whatsapp_router._extract_incoming_messages(_v2(msg, phone="447700900123"))
    assert m["phone_number"] == "447700900123"


def test_outbound_echo_is_ignored():
    msg = {"id": "wamid.12", "type": "text", "to": "447911123456", "text": {"body": "On my way"},
           "kapso": {"direction": "outbound", "status": "sent"}}
    assert whatsapp_router._extract_incoming_messages(_v2(msg)) == []


class _Req:
    def __init__(self, body: bytes):
        self._body = body

    async def body(self):
        return self._body


def _sign(secret, body):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_status_event_from_header_is_not_processed(monkeypatch):
    monkeypatch.setattr(whatsapp_router.settings, "KAPSO_WEBHOOK_SECRET", "s3cret")
    body = json.dumps(_v2()).encode()
    out = asyncio.run(
        whatsapp_router._handle_kapso_webhook(
            _Req(body), _sign("s3cret", body), route_hint="webhook",
            webhook_event="whatsapp.message.delivered",
        )
    )
    assert out["processed"] == 0
    assert out["event"] == "whatsapp.message.delivered"


def test_missing_secret_rejects(monkeypatch):
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(whatsapp_router.settings, "KAPSO_WEBHOOK_SECRET", "")
    body = json.dumps(_v2()).encode()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(whatsapp_router._handle_kapso_webhook(_Req(body), None, route_hint="webhook"))
    assert exc.value.status_code == 401
