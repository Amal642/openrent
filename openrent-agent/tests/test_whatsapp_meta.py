"""Direct Meta WhatsApp Cloud API transport (Kapso exit, phase 1).

- native Meta webhook payloads parse into handler kwargs (incl. batches)
- delivery statuses / reactions / foreign numbers are never treated as leads
- X-Hub-Signature-256 is checked against the app secret (fail closed)
- the GET subscription handshake echoes hub.challenge only for our token
- shadow mode parses but never reaches the handler; live mode queues it
- outbound uses graph.facebook.com + Bearer token when WHATSAPP_PROVIDER=meta
"""
import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException

from app.api import whatsapp_router
from app.whatsapp import kapso_worker, meta_webhook
from app.whatsapp.kapso_worker import KapsoWhatsAppWorker

PNID = "1334185119782926"


def _msg(**overrides):
    item = {
        "from": "447911123456",
        "id": "wamid.ABC",
        "timestamp": "1730092800",
        "type": "text",
        "text": {"body": "Hi, it's about the flat on Elm Road"},
    }
    item.update(overrides)
    return item


def _payload(messages=None, statuses=None, contacts=None, pnid=PNID):
    value = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "447783129181", "phone_number_id": pnid},
    }
    if contacts is None:
        contacts = [{"wa_id": "447911123456", "profile": {"name": "John Doe"}}]
    if messages is not None:
        value["messages"] = messages
        value["contacts"] = contacts
    if statuses is not None:
        value["statuses"] = statuses
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "2611207395968870", "changes": [{"field": "messages", "value": value}]}],
    }


def _sign(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class _Background:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


# ── Parsing ──────────────────────────────────────────────────────────────────

def test_text_message_parsed_with_profile_name():
    [m] = meta_webhook.extract_incoming_messages(_payload([_msg()]))
    assert m == {
        "phone_number": "447911123456",
        "message": "Hi, it's about the flat on Elm Road",
        "timestamp": 1730092800,
        "sender_name": "John Doe",
        "message_id": "wamid.ABC",
        "phone_number_id": PNID,
    }


def test_batched_messages_all_extracted_in_order():
    msgs = [_msg(id="wamid.1", text={"body": "first"}), _msg(id="wamid.2", text={"body": "second"})]
    out = meta_webhook.extract_incoming_messages(_payload(msgs))
    assert [m["message"] for m in out] == ["first", "second"]


def test_statuses_only_payload_yields_nothing():
    statuses = [{"id": "wamid.OUT", "status": "delivered", "recipient_id": "447911123456"}]
    assert meta_webhook.extract_incoming_messages(_payload(statuses=statuses)) == []


def test_reaction_and_system_messages_skipped():
    msgs = [
        _msg(type="reaction", reaction={"message_id": "wamid.OUT", "emoji": "👍"}),
        _msg(type="system", system={"body": "changed number"}),
    ]
    assert meta_webhook.extract_incoming_messages(_payload(msgs)) == []


def test_image_caption_used_and_uncaptioned_media_gets_placeholder():
    msgs = [
        _msg(id="wamid.i1", type="image", image={"id": "media1", "caption": "the kitchen"}),
        _msg(id="wamid.a1", type="audio", audio={"id": "media2"}),
    ]
    out = meta_webhook.extract_incoming_messages(_payload(msgs))
    assert [m["message"] for m in out] == ["the kitchen", "[audio message]"]


def test_interactive_button_reply_uses_title():
    msg = _msg(type="interactive", interactive={"type": "button_reply", "button_reply": {"id": "b1", "title": "Yes"}})
    [m] = meta_webhook.extract_incoming_messages(_payload([msg]))
    assert m["message"] == "Yes"


def test_non_whatsapp_object_ignored():
    payload = _payload([_msg()])
    payload["object"] = "page"
    assert meta_webhook.extract_incoming_messages(payload) == []


def test_missing_contacts_gives_no_sender_name():
    [m] = meta_webhook.extract_incoming_messages(_payload([_msg()], contacts=[]))
    assert m["sender_name"] is None


# ── Signature + handshake ────────────────────────────────────────────────────

def test_signature_valid_and_invalid(monkeypatch):
    monkeypatch.setattr(meta_webhook.settings, "META_APP_SECRET", "appsecret")
    body = b'{"object":"whatsapp_business_account"}'
    assert meta_webhook.signature_is_valid(body, _sign("appsecret", body))
    assert not meta_webhook.signature_is_valid(body, _sign("wrong", body))
    assert not meta_webhook.signature_is_valid(body, None)


def test_missing_app_secret_fails_closed(monkeypatch):
    monkeypatch.setattr(meta_webhook.settings, "META_APP_SECRET", "")
    body = b"{}"
    assert not meta_webhook.signature_is_valid(body, _sign("", body))


def test_verify_challenge(monkeypatch):
    monkeypatch.setattr(meta_webhook.settings, "META_WEBHOOK_VERIFY_TOKEN", "vtok")
    assert meta_webhook.verify_challenge("subscribe", "vtok", "12345") == "12345"
    assert meta_webhook.verify_challenge("subscribe", "nope", "12345") is None
    assert meta_webhook.verify_challenge("unsubscribe", "vtok", "12345") is None


def test_verify_challenge_rejects_when_token_unset(monkeypatch):
    monkeypatch.setattr(meta_webhook.settings, "META_WEBHOOK_VERIFY_TOKEN", "")
    assert meta_webhook.verify_challenge("subscribe", "", "12345") is None


# ── Endpoint behaviour ───────────────────────────────────────────────────────

def _configure(monkeypatch, mode, pnid=PNID):
    monkeypatch.setattr(whatsapp_router.settings, "META_APP_SECRET", "appsecret")
    monkeypatch.setattr(whatsapp_router.settings, "META_WEBHOOK_MODE", mode)
    monkeypatch.setattr(whatsapp_router.settings, "META_WA_PHONE_NUMBER_ID", pnid)


def _call(payload, secret="appsecret"):
    body = json.dumps(payload).encode()
    bg = _Background()
    out = asyncio.run(whatsapp_router._handle_meta_webhook(body, _sign(secret, body), bg))
    return out, bg


def test_shadow_mode_parses_but_never_queues_handler(monkeypatch):
    _configure(monkeypatch, "shadow")
    out, bg = _call(_payload([_msg()]))
    assert out["mode"] == "shadow" and out["parsed"] == 1 and out["processed"] == 0
    assert bg.tasks == []


def test_live_mode_queues_messages(monkeypatch):
    _configure(monkeypatch, "live")
    out, bg = _call(_payload([_msg()]))
    assert out["processed"] == 1
    [(fn, args, _)] = bg.tasks
    assert fn is whatsapp_router._process_meta_messages
    assert args[0][0]["message_id"] == "wamid.ABC"


def test_live_mode_ignores_other_phone_number_ids(monkeypatch):
    _configure(monkeypatch, "live")
    out, bg = _call(_payload([_msg()], pnid="999"))
    assert out["processed"] == 0
    assert bg.tasks == []


def test_bad_signature_rejected(monkeypatch):
    _configure(monkeypatch, "live")
    with pytest.raises(HTTPException) as exc:
        _call(_payload([_msg()]), secret="wrong")
    assert exc.value.status_code == 401


def test_process_strips_phone_number_id_before_handler(monkeypatch):
    calls = []

    async def fake_handle(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("app.whatsapp.handler.handle_incoming_message", fake_handle)
    [m] = meta_webhook.extract_incoming_messages(_payload([_msg()]))
    asyncio.run(whatsapp_router._process_meta_messages([m]))
    assert calls and "phone_number_id" not in calls[0]
    assert calls[0]["phone_number"] == "447911123456"


def test_process_continues_after_handler_error(monkeypatch):
    seen = []

    async def flaky(**kwargs):
        seen.append(kwargs["message_id"])
        if kwargs["message_id"] == "wamid.1":
            raise RuntimeError("boom")

    monkeypatch.setattr("app.whatsapp.handler.handle_incoming_message", flaky)
    msgs = meta_webhook.extract_incoming_messages(
        _payload([_msg(id="wamid.1"), _msg(id="wamid.2")])
    )
    asyncio.run(whatsapp_router._process_meta_messages(msgs))
    assert seen == ["wamid.1", "wamid.2"]


# ── Outbound provider switch ─────────────────────────────────────────────────

def _fake_send(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = '{"messages":[{"id":"wamid.OUT"}]}'

    class FakeClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, headers, json):
            captured.update(url=url, headers=headers, json=json)
            return FakeResponse()

    async def no_publish(self):
        return None

    monkeypatch.setattr("app.whatsapp.kapso_worker.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr(KapsoWhatsAppWorker, "_publish_status", no_publish)
    return captured


def test_meta_provider_sends_to_graph_with_bearer(monkeypatch):
    captured = _fake_send(monkeypatch)
    s = kapso_worker.settings
    monkeypatch.setattr(s, "WHATSAPP_PROVIDER", "meta")
    monkeypatch.setattr(s, "META_GRAPH_BASE_URL", "https://graph.facebook.com/v24.0")
    monkeypatch.setattr(s, "META_WA_ACCESS_TOKEN", "EAAtoken")
    monkeypatch.setattr(s, "META_WA_PHONE_NUMBER_ID", PNID)
    monkeypatch.setattr(s, "KAPSO_API_KEY", "kapso-key")

    worker = KapsoWhatsAppWorker()
    worker.status = "connected"
    assert asyncio.run(worker.send_message("+44 7700 900000", "Hello!")) is True
    assert captured["url"] == f"https://graph.facebook.com/v24.0/{PNID}/messages"
    assert captured["headers"] == {"Authorization": "Bearer EAAtoken"}
    assert captured["json"]["to"] == "447700900000"
    assert captured["json"]["text"] == {"body": "Hello!"}


def test_default_provider_still_kapso(monkeypatch):
    captured = _fake_send(monkeypatch)
    s = kapso_worker.settings
    monkeypatch.setattr(s, "WHATSAPP_PROVIDER", "kapso")
    monkeypatch.setattr(s, "KAPSO_BASE_URL", "https://api.kapso.ai/meta/whatsapp/v24.0")
    monkeypatch.setattr(s, "KAPSO_API_KEY", "kapso-key")
    monkeypatch.setattr(s, "KAPSO_PHONE_NUMBER_ID", "kpnid")

    worker = KapsoWhatsAppWorker()
    worker.status = "connected"
    assert asyncio.run(worker.send_message("447700900000", "Hi")) is True
    assert captured["url"] == "https://api.kapso.ai/meta/whatsapp/v24.0/kpnid/messages"
    assert captured["headers"] == {"X-API-Key": "kapso-key"}


def test_meta_provider_start_requires_meta_env(monkeypatch):
    async def no_publish(self):
        return None

    s = kapso_worker.settings
    monkeypatch.setattr(KapsoWhatsAppWorker, "_publish_status", no_publish)
    monkeypatch.setattr(s, "WHATSAPP_PROVIDER", "meta")
    monkeypatch.setattr(s, "META_WA_ACCESS_TOKEN", "")
    monkeypatch.setattr(s, "META_WA_PHONE_NUMBER_ID", PNID)
    monkeypatch.setattr(s, "KAPSO_API_KEY", "kapso-key")
    monkeypatch.setattr(s, "KAPSO_PHONE_NUMBER_ID", "kpnid")

    worker = KapsoWhatsAppWorker()
    asyncio.run(worker.start())
    assert worker.status == "error"
    assert "META_WA_ACCESS_TOKEN" in worker.last_error
