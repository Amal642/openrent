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
