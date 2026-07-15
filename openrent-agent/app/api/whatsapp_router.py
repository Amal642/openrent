"""FastAPI router for WhatsApp Acquisition endpoints.

Endpoints:
  POST /api/whatsapp/webhook      — Kapso webhook for incoming/sent/status events
  POST /api/whatsapp/incoming     — Kapso incoming webhook alias
  POST /api/whatsapp/sent         — Kapso sent/status webhook alias
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

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse
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
        logger.warning("WHATSAPP_KAPSO_WEBHOOK_SECRET_NOT_SET accepting_unsigned_webhook=True")
        return True
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

    extracted = []
    for item in _message_items(payload):
        text = _first_value(
            item,
            [
                ("text", "body"),
                ("text",),
                ("body",),
                ("message",),
                ("content",),
            ],
        )
        if isinstance(text, dict):
            text = text.get("body")
        if not text:
            continue

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
        )
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
        ) or _first_value(first_contact, [("profile", "name"), ("name",)])

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
            }
        )
    return extracted


async def _handle_kapso_webhook(
    request: Request,
    x_webhook_signature: str | None,
    route_hint: str,
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

    event = str(payload.get("event") or route_hint or "").lower()
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
):
    """Kapso incoming webhook alias."""
    return await _handle_kapso_webhook(
        request,
        x_webhook_signature,
        route_hint="incoming",
    )


@router.post("/webhook")
async def whatsapp_kapso_webhook(
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
):
    """Kapso webhook for incoming and sent/status events."""
    return await _handle_kapso_webhook(
        request,
        x_webhook_signature,
        route_hint="webhook",
    )


@router.post("/sent")
async def whatsapp_sent(
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
):
    """Kapso sent/status webhook alias."""
    return await _handle_kapso_webhook(
        request,
        x_webhook_signature,
        route_hint="sent",
    )


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
