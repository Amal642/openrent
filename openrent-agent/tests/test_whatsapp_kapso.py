import asyncio

from app.api import whatsapp_router
from app.whatsapp.kapso_worker import KapsoWhatsAppWorker


def test_kapso_extracts_incoming_meta_style_message():
    payload = {
        "event": "message.received",
        "occurred_at": "2026-06-27T14:30:00.000000Z",
        "data": {
            "contacts": [
                {
                    "wa_id": "447700900000",
                    "profile": {"name": "Jess"},
                }
            ],
            "messages": [
                {
                    "id": "wamid.test",
                    "from": "447700900000",
                    "timestamp": "1782570600",
                    "text": {"body": "Hello there"},
                }
            ],
        },
    }

    messages = whatsapp_router._extract_incoming_messages(payload)

    assert messages == [
        {
            "phone_number": "447700900000",
            "message": "Hello there",
            "timestamp": 1782570600,
            "sender_name": "Jess",
            "jid": None,
            "lid": None,
            "message_id": "wamid.test",
        }
    ]


def test_kapso_worker_sends_expected_payload(monkeypatch):
    captured = {}

    async def fake_publish_status(self):
        return None

    class FakeResponse:
        status_code = 200
        text = '{"ok":true}'

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(
        "app.whatsapp.kapso_worker.settings.KAPSO_BASE_URL",
        "https://api.kapso.ai/meta/whatsapp/v24.0",
    )
    monkeypatch.setattr("app.whatsapp.kapso_worker.settings.KAPSO_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.whatsapp.kapso_worker.settings.KAPSO_PHONE_NUMBER_ID",
        "phone-number-id",
    )
    monkeypatch.setattr("app.whatsapp.kapso_worker.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(
        "app.whatsapp.kapso_worker.KapsoWhatsAppWorker._publish_status",
        fake_publish_status,
    )

    worker = KapsoWhatsAppWorker()
    worker.status = "connected"

    ok = asyncio.run(worker.send_message("+44 7700 900000", "Hello!"))

    assert ok is True
    assert captured["url"] == (
        "https://api.kapso.ai/meta/whatsapp/v24.0/phone-number-id/messages"
    )
    assert captured["headers"] == {"X-API-Key": "test-key"}
    assert captured["json"] == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "447700900000",
        "type": "text",
        "text": {"body": "Hello!"},
    }


def test_kapso_worker_scrubs_ai_dashes_before_send(monkeypatch):
    captured = {}

    async def fake_publish_status(self):
        return None

    class FakeResponse:
        status_code = 200
        text = '{"ok":true}'

    class FakeClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers, json):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.whatsapp.kapso_worker.settings.KAPSO_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.whatsapp.kapso_worker.settings.KAPSO_PHONE_NUMBER_ID",
        "phone-number-id",
    )
    monkeypatch.setattr("app.whatsapp.kapso_worker.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(
        "app.whatsapp.kapso_worker.KapsoWhatsAppWorker._publish_status",
        fake_publish_status,
    )

    worker = KapsoWhatsAppWorker()
    worker.status = "connected"

    # Real output from build_property_ask in the 2026-09-29 sandbox test.
    leaked = (
        "Hey, my wife usually deals with our OpenRent messages\u2014can you let me "
        "know which property you're asking about? Free 3\u20135pm"
    )
    ok = asyncio.run(worker.send_message("447700900000", leaked))

    assert ok is True
    assert captured["json"]["text"]["body"] == (
        "Hey, my wife usually deals with our OpenRent messages, can you let me "
        "know which property you're asking about? Free 3-5pm"
    )


def test_schedule_reply_stores_and_dedupes_scrubbed_text(monkeypatch):
    from app.whatsapp import handler

    seen = {}

    def fake_exists(contact_id, message):
        seen["dedupe_checked"] = message
        return False

    def fake_update(contact_id, **fields):
        seen["fields"] = fields

    monkeypatch.setattr(handler, "outbound_message_exists", fake_exists)
    monkeypatch.setattr(handler, "outbound_message_count", lambda contact_id: 0)
    monkeypatch.setattr(handler, "update_contact", fake_update)
    monkeypatch.setattr(handler, "next_reply_time", lambda: "later")
    monkeypatch.setattr(handler.settings, "WHATSAPP_AUTO_REPLY_ENABLED", True)

    handler._schedule_reply(1, "Thanks \u2014 which property is it?", "AWAITING_PROPERTY")

    assert seen["dedupe_checked"] == "Thanks, which property is it?"
    assert seen["fields"]["last_ai_reply"] == "Thanks, which property is it?"
