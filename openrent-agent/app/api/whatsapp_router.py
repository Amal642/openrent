"""FastAPI router for WhatsApp Acquisition endpoints.

Endpoints:
  POST /api/whatsapp/webhook      — Kapso webhook for incoming/sent/status events
  POST /api/whatsapp/incoming     — Kapso incoming webhook alias
  POST /api/whatsapp/sent         — Kapso sent/status webhook alias
  GET  /api/whatsapp/meta/webhook — Meta Cloud API subscription handshake
  POST /api/whatsapp/meta/webhook — Meta Cloud API webhook (shadow or live)
  GET  /api/whatsapp/contacts     — dashboard list
  POST /api/whatsapp/contacts     — manual contact entry
  PATCH /api/whatsapp/contacts/:id — edit contact
  GET  /api/whatsapp/status       — Kapso worker status
  POST /api/whatsapp/reconnect    — restart Kapso dispatch worker
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from app.config import settings
from app.utils.logger import logger
from app.whatsapp.repository import (
    create_manual_contact,
    get_all_contacts,
    get_contact_by_phone,
    resolve_lid_to_phone,
    update_contact,
)

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

QR_FILE = Path("whatsapp-qr.png")


def _signature_is_valid(raw_body: bytes, signature: str | None) -> bool:
    secret = settings.KAPSO_WEBHOOK_SECRET
    if not secret:
        # Fail closed: without a secret anyone could post fake landlord messages.
        logger.error("WHATSAPP_KAPSO_WEBHOOK_SECRET_NOT_SET rejecting_webhook=True")
        return False
    if not signature:
        return False

    supplied = signature.strip()
    if supplied.lower().startswith("sha256="):
        supplied = supplied.split("=", 1)[1].strip()

    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    candidates = {
        digest.hex(),
        base64.b64encode(digest).decode(),
    }
    return any(hmac.compare_digest(supplied, candidate) for candidate in candidates)


def _dig(data: Any, *path: str) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_value(data: dict, paths: list[tuple[str, ...]]) -> Any:
    for path in paths:
        value = _dig(data, *path)
        if value not in (None, ""):
            return value
    return None


def _normalize_timestamp(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        pass
    if isinstance(value, str):
        try:
            from datetime import datetime

            cleaned = value.replace("Z", "+00:00")
            return int(datetime.fromisoformat(cleaned).timestamp())
        except Exception:
            return None
    return None


def _message_items(payload: dict) -> list[dict]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    candidates = [
        data.get("messages") if isinstance(data, dict) else None,
        payload.get("messages"),
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]

    for candidate in (
        data.get("message") if isinstance(data, dict) else None,
        payload.get("message"),
        data,
    ):
        if isinstance(candidate, dict):
            return [candidate]
    return []


def _extract_incoming_messages(payload: dict) -> list[dict]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    contacts = data.get("contacts") if isinstance(data.get("contacts"), list) else []
    first_contact = contacts[0] if contacts and isinstance(contacts[0], dict) else {}

    # Kapso v2 puts contact data on a top-level "conversation" object.
    conversation = payload.get("conversation") if isinstance(payload.get("conversation"), dict) else {}

    extracted = []
    for item in _message_items(payload):
        # Our own outbound messages echoed back are never landlord messages.
        if str(_dig(item, "kapso", "direction") or "").lower() == "outbound":
            continue

        text = _first_value(
            item,
            [
                ("text", "body"),
                ("text",),
                ("body",),
                ("message",),
                ("content",),
                ("kapso", "content"),
                ("kapso", "transcript"),
            ],
        )
        if isinstance(text, dict):
            text = text.get("body")
        if not text:
            # Voice note / photo / location with no caption: the sender's number
            # IS the lead, so keep the message with a placeholder instead of
            # dropping the contact entirely.
            msg_type = item.get("type")
            if not msg_type or msg_type == "text":
                continue
            text = f"[{msg_type} message]"

        phone = _first_value(
            item,
            [
                ("from",),
                ("phone",),
                ("phone_number",),
                ("wa_id",),
                ("sender", "phone"),
                ("sender", "phone_number"),
                ("contact", "phone"),
                ("contact", "wa_id"),
            ],
        ) or _first_value(
            first_contact,
            [
                ("wa_id",),
                ("phone",),
                ("phone_number",),
            ],
        ) or _first_value(conversation, [("phone_number",)])
        if not phone:
            continue

        sender_name = _first_value(
            item,
            [
                ("profile", "name"),
                ("sender", "name"),
                ("contact", "name"),
                ("sender_name",),
                ("name",),
            ],
        ) or _first_value(first_contact, [("profile", "name"), ("name",)]) or _first_value(
            conversation, [("contact_name",)]
        )

        extracted.append(
            {
                "phone_number": str(phone),
                "message": str(text),
                "timestamp": _normalize_timestamp(
                    _first_value(item, [("timestamp",), ("created_at",), ("sent_at",)])
                    or payload.get("occurred_at")
                ),
                "sender_name": sender_name,
                "jid": _first_value(item, [("jid",)]),
                "lid": _first_value(item, [("lid",)]),
                "message_id": _first_value(item, [("id",), ("message_id",)]),
                # Kapso v2 carries our receiving number at the top level.
                "line_phone_number_id": _first_value(
                    payload,
                    [
                        ("phone_number_id",),
                        ("conversation", "phone_number_id"),
                        ("data", "metadata", "phone_number_id"),
                    ],
                ),
            }
        )
    return extracted


async def _handle_kapso_webhook(
    request: Request,
    x_webhook_signature: str | None,
    route_hint: str,
    webhook_event: str | None = None,
) -> dict:
    raw_body = await request.body()
    if not _signature_is_valid(raw_body, x_webhook_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body.decode() or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    # Kapso v2 sends the event name in the X-Webhook-Event header, not the body.
    event = str(webhook_event or payload.get("event") or route_hint or "").lower()
    if route_hint == "sent" or any(
        token in event for token in ("sent", "status", "delivered", "read", "failed")
    ):
        logger.info(
            f"WHATSAPP_KAPSO_WEBHOOK_SENT event={event!r} "
            f"id={payload.get('id')!r}"
        )
        return {"status": "ok", "event": event, "processed": 0}

    messages = _extract_incoming_messages(payload)
    if not messages:
        logger.info(
            f"WHATSAPP_KAPSO_WEBHOOK_IGNORED event={event!r} "
            "reason=no incoming text message found"
        )
        return {"status": "ignored", "event": event, "processed": 0}

    from app.whatsapp.handler import handle_incoming_message

    for message in messages:
        await handle_incoming_message(**message)

    logger.info(
        f"WHATSAPP_KAPSO_WEBHOOK_PROCESSED event={event!r} count={len(messages)}"
    )
    return {"status": "ok", "event": event, "processed": len(messages)}


# ── Worker status & control ────────────────────────────────────────────────────

@router.get("/status")
def whatsapp_status():
    """Return current Kapso worker state."""
    from app.whatsapp.browser_worker import get_worker
    data = get_worker().get_status_dict()
    # Embed QR as base64 so the frontend doesn't need a separate image request
    if data.get("qr_available") and QR_FILE.exists():
        import base64
        try:
            data["qr_b64"] = base64.b64encode(QR_FILE.read_bytes()).decode()
        except Exception:
            pass
    return data


@router.get("/qr")
def whatsapp_qr():
    """QR codes are not used by the Kapso API transport."""
    raise HTTPException(status_code=404, detail="Kapso transport does not use QR login")


DIAG_FILE = Path("whatsapp-diag.png")


@router.get("/diag")
def whatsapp_diag():
    """Serve the last diagnostic screenshot (captured on load timeout)."""
    if not DIAG_FILE.exists():
        raise HTTPException(status_code=404, detail="No diagnostic screenshot available")
    return FileResponse(str(DIAG_FILE), media_type="image/png")


@router.post("/reconnect")
async def whatsapp_reconnect():
    """Restart the Kapso dispatch worker."""
    from app.whatsapp.browser_worker import get_worker
    worker = get_worker()
    logger.info("WHATSAPP_KAPSO_FORCE_RECONNECT_REQUESTED via=dashboard")
    import asyncio
    asyncio.create_task(worker.force_reconnect(), name="wa-force-reconnect")
    return {"status": "reconnecting"}


class ProxyPayload(BaseModel):
    proxy_id: Optional[int] = None


@router.post("/proxy")
async def whatsapp_set_proxy(payload: ProxyPayload):
    """Kept for dashboard compatibility. Kapso does not use browser proxies."""
    from app.whatsapp.browser_worker import get_worker

    get_worker().set_proxy(payload.proxy_id)
    return {
        "status": "ignored",
        "proxy_id": payload.proxy_id,
        "note": "Kapso API transport does not use browser proxies",
    }


# ── Kapso webhook endpoints ───────────────────────────────────────────────────

class ResolveLidPayload(BaseModel):
    lid: str
    phone: str
    jid: Optional[str] = None


class NodeLogPayload(BaseModel):
    level: str
    message: str


@router.post("/incoming")
async def whatsapp_incoming(
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
    x_webhook_event: str | None = Header(default=None),
):
    """Kapso incoming webhook alias."""
    return await _handle_kapso_webhook(
        request,
        x_webhook_signature,
        route_hint="incoming",
        webhook_event=x_webhook_event,
    )


@router.post("/webhook")
async def whatsapp_kapso_webhook(
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
    x_webhook_event: str | None = Header(default=None),
):
    """Kapso webhook for incoming and sent/status events."""
    return await _handle_kapso_webhook(
        request,
        x_webhook_signature,
        route_hint="webhook",
        webhook_event=x_webhook_event,
    )


@router.post("/sent")
async def whatsapp_sent(
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
    x_webhook_event: str | None = Header(default=None),
):
    """Kapso sent/status webhook alias."""
    return await _handle_kapso_webhook(
        request,
        x_webhook_signature,
        route_hint="sent",
        webhook_event=x_webhook_event,
    )


# ── Direct Meta Cloud API webhook ─────────────────────────────────────────────

async def _process_meta_messages(messages: list[dict]) -> None:
    from app.whatsapp.handler import handle_incoming_message

    # Sequential, in delivery order, so a landlord's two quick messages are
    # captured in the order they were sent.
    for message in messages:
        try:
            await handle_incoming_message(**message)
        except Exception as exc:
            logger.error(
                f"WHATSAPP_META_HANDLER_ERROR phone={message.get('phone_number')} "
                f"message_id={message.get('message_id')} error={exc}"
            )


async def _handle_meta_webhook(
    raw_body: bytes,
    signature: str | None,
    background: BackgroundTasks,
) -> dict:
    from app.whatsapp import meta_webhook

    if not meta_webhook.signature_is_valid(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw_body.decode() or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    from app.whatsapp.lines import accepted_phone_number_ids

    messages = meta_webhook.extract_incoming_messages(payload)
    ours = accepted_phone_number_ids()
    if ours:
        foreign = [m for m in messages if str(m.get("line_phone_number_id")) not in ours]
        for m in foreign:
            logger.info(
                f"WHATSAPP_META_WEBHOOK_OTHER_NUMBER "
                f"phone_number_id={m.get('line_phone_number_id')} "
                f"message_id={m.get('message_id')}"
            )
        messages = [m for m in messages if str(m.get("line_phone_number_id")) in ours]

    if not messages:
        # Delivery receipts (statuses) and non-message changes land here.
        return {"status": "ok", "processed": 0}

    mode = settings.META_WEBHOOK_MODE
    if mode != "live":
        for m in messages:
            logger.info(
                f"WHATSAPP_META_WEBHOOK_SHADOW phone={m['phone_number']} "
                f"phone_number_id={m.get('line_phone_number_id')} "
                f"message_id={m.get('message_id')} sender_name={m.get('sender_name')!r} "
                f"message_len={len(m['message'])}"
            )
        return {"status": "ok", "mode": "shadow", "processed": 0, "parsed": len(messages)}

    # Ack fast: Meta retries slow/failed deliveries, and the handler can make
    # AI calls. Redeliveries are deduped on message_id in the handler.
    background.add_task(_process_meta_messages, messages)
    logger.info(f"WHATSAPP_META_WEBHOOK_QUEUED count={len(messages)}")
    return {"status": "ok", "mode": "live", "processed": len(messages)}


@router.get("/meta/webhook")
def whatsapp_meta_verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    """Meta's webhook subscription handshake: echo hub.challenge if the token matches."""
    from app.whatsapp.meta_webhook import verify_challenge

    challenge = verify_challenge(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        logger.warning(f"WHATSAPP_META_VERIFY_REJECTED mode={hub_mode!r}")
        raise HTTPException(status_code=403, detail="Verification failed")
    logger.info("WHATSAPP_META_VERIFY_OK")
    return PlainTextResponse(challenge)


@router.post("/meta/webhook")
async def whatsapp_meta_webhook(
    request: Request,
    background: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
):
    """Direct Meta Cloud API webhook (inbound messages + delivery statuses)."""
    return await _handle_meta_webhook(await request.body(), x_hub_signature_256, background)


@router.post("/resolve")
async def whatsapp_resolve_lid(payload: ResolveLidPayload):
    contact = resolve_lid_to_phone(payload.lid, payload.phone, payload.jid)
    logger.info(
        f"WHATSAPP_LID_RESOLVED lid={payload.lid} phone={payload.phone} "
        f"contact_id={getattr(contact, 'id', None)}"
    )
    return {"status": "ok", "contact_id": getattr(contact, "id", None)}


@router.post("/log")
async def whatsapp_node_log(payload: NodeLogPayload):
    level = payload.level.lower()
    msg = f"WHATSAPP_NODE {payload.message}"
    if level == "error":
        logger.error(msg)
    elif level == "warn":
        logger.warning(msg)
    else:
        logger.info(msg)
    return {"status": "ok"}


# ── Contacts ──────────────────────────────────────────────────────────────────

@router.get("/contacts")
def whatsapp_contacts(limit: int = 200):
    return get_all_contacts(limit=limit)


class ManualContactPayload(BaseModel):
    phone: str
    name: Optional[str] = None
    property_address: Optional[str] = None


class EditContactPayload(BaseModel):
    phone: Optional[str] = None
    name: Optional[str] = None
    property_address: Optional[str] = None


@router.post("/contacts")
def whatsapp_create_manual_contact(payload: ManualContactPayload):
    phone = payload.phone.strip().lstrip("+").replace(" ", "")
    if not phone:
        raise HTTPException(status_code=400, detail="phone is required")
    contact = create_manual_contact(phone, payload.name, payload.property_address)
    return {"status": "ok", "id": contact.id}


@router.patch("/contacts/{contact_id}")
def whatsapp_edit_contact(contact_id: int, payload: EditContactPayload):
    updates: dict = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip() or None
    if payload.property_address is not None:
        updates["property_address"] = payload.property_address.strip() or None
    if payload.phone is not None:
        new_phone = payload.phone.strip().lstrip("+").replace(" ", "")
        if new_phone:
            existing = get_contact_by_phone(new_phone)
            if existing and existing.id != contact_id:
                raise HTTPException(status_code=409, detail="Phone number already exists")
            updates["phone_number"] = new_phone
            updates["status"] = "PHONE_ACQUIRED"
            updates["is_manual"] = True

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    contact = update_contact(contact_id, **updates)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"status": "ok", "id": contact.id}


# ── Stub lifecycle functions (main.py imports these) ──────────────────────────
# Dispatch is now inside the Kapso worker — these are no-ops kept for
# backwards-compatibility with the existing main.py lifespan wiring.

def start_whatsapp_reply_dispatcher():
    logger.info("WHATSAPP_REPLY_DISPATCHER_STUB dispatch_handled_by=kapso_worker")
    return None


async def stop_whatsapp_reply_dispatcher(task):
    pass
