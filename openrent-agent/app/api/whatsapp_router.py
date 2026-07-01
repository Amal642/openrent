"""
FastAPI router for WhatsApp Acquisition endpoints.

Endpoints:
  POST /api/whatsapp/incoming     — legacy Baileys webhook (kept for compatibility)
  GET  /api/whatsapp/contacts     — dashboard list
  POST /api/whatsapp/contacts     — manual contact entry
  PATCH /api/whatsapp/contacts/:id — edit contact
  GET  /api/whatsapp/status       — browser worker status
  GET  /api/whatsapp/qr           — QR code PNG (when needs_scan)
  POST /api/whatsapp/reconnect    — force reconnect
  POST /api/whatsapp/proxy        — assign proxy to worker
  POST /api/whatsapp/log          — receive log line from Node service (legacy)

Background:
  Dispatch and polling are now handled inside WhatsAppWebWorker._poll_loop().
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

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


# ── Worker status & control ────────────────────────────────────────────────────

@router.get("/status")
def whatsapp_status():
    """Return current browser worker state."""
    from app.whatsapp.browser_worker import get_worker
    return get_worker().get_status_dict()


@router.get("/qr")
def whatsapp_qr():
    """Serve the QR code PNG when the session needs scanning."""
    from app.whatsapp.browser_worker import get_worker
    worker = get_worker()
    if not QR_FILE.exists():
        raise HTTPException(status_code=404, detail="No QR code available")
    if worker.status not in ("needs_scan", "starting"):
        raise HTTPException(status_code=409, detail=f"Worker status is '{worker.status}', not needs_scan")
    return FileResponse(str(QR_FILE), media_type="image/png")


DIAG_FILE = Path("whatsapp-diag.png")


@router.get("/diag")
def whatsapp_diag():
    """Serve the last diagnostic screenshot (captured on load timeout)."""
    if not DIAG_FILE.exists():
        raise HTTPException(status_code=404, detail="No diagnostic screenshot available")
    return FileResponse(str(DIAG_FILE), media_type="image/png")


@router.post("/reconnect")
async def whatsapp_reconnect():
    """Force a full browser reconnect (clears session if needed)."""
    from app.whatsapp.browser_worker import get_worker
    worker = get_worker()
    logger.info("WHATSAPP_WEB_FORCE_RECONNECT_REQUESTED via=dashboard")
    import asyncio
    asyncio.create_task(worker.force_reconnect(), name="wa-force-reconnect")
    return {"status": "reconnecting"}


class ProxyPayload(BaseModel):
    proxy_id: Optional[int] = None


@router.post("/proxy")
async def whatsapp_set_proxy(payload: ProxyPayload):
    """Assign or clear the proxy used by the browser worker. Takes effect on next reconnect."""
    from app.whatsapp.browser_worker import get_worker
    worker = get_worker()
    worker.set_proxy(payload.proxy_id)

    if payload.proxy_id:
        try:
            from app.db.repository import get_proxy
            proxy = get_proxy(payload.proxy_id)  # returns a dict
            if not proxy:
                raise HTTPException(status_code=404, detail="Proxy not found")
            host = proxy.get("host") if isinstance(proxy, dict) else getattr(proxy, "host", "?")
            logger.info(
                f"WHATSAPP_WEB_PROXY_ASSIGNED proxy_id={payload.proxy_id} "
                f"host={host} — reconnecting to apply"
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"WHATSAPP_WEB_PROXY_LOOKUP_FAILED error={exc}")
    else:
        logger.info("WHATSAPP_WEB_PROXY_CLEARED — running without proxy")

    import asyncio
    asyncio.create_task(worker.force_reconnect(), name="wa-proxy-reconnect")
    return {"status": "ok", "proxy_id": payload.proxy_id, "note": "reconnecting to apply"}


# ── Legacy Baileys endpoints (kept so old server.js doesn't 404) ──────────────

class IncomingMessagePayload(BaseModel):
    phone: str
    message: str
    timestamp: Optional[int] = None
    sender_name: Optional[str] = None
    jid: Optional[str] = None
    lid: Optional[str] = None
    message_id: Optional[str] = None


class ResolveLidPayload(BaseModel):
    lid: str
    phone: str
    jid: Optional[str] = None


class NodeLogPayload(BaseModel):
    level: str
    message: str


@router.post("/incoming")
async def whatsapp_incoming(payload: IncomingMessagePayload):
    """Legacy Baileys webhook — still functional if Baileys is running alongside."""
    from app.whatsapp.handler import handle_incoming_message
    await handle_incoming_message(
        phone_number=payload.phone,
        message=payload.message,
        timestamp=payload.timestamp,
        sender_name=payload.sender_name,
        jid=payload.jid,
        lid=payload.lid,
        message_id=payload.message_id,
    )
    return {"status": "ok"}


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
# Dispatch is now inside the browser worker — these are no-ops kept for
# backwards-compatibility with the existing main.py lifespan wiring.

def start_whatsapp_reply_dispatcher():
    logger.info("WHATSAPP_REPLY_DISPATCHER_STUB dispatch_handled_by=browser_worker")
    return None


async def stop_whatsapp_reply_dispatcher(task):
    pass
