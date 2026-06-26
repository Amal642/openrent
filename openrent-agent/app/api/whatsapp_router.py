"""
FastAPI router for WhatsApp Acquisition endpoints.

Endpoints:
  POST /api/whatsapp/incoming  — Baileys webhook
  GET  /api/whatsapp/contacts  — dashboard list

Background:
  whatsapp_reply_dispatcher — checks due contacts every 30s and sends replies
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.utils.logger import logger
from app.whatsapp.reply import send_whatsapp_message
from app.whatsapp.repository import (
    create_manual_contact,
    get_all_contacts,
    get_contact_by_phone,
    get_due_contacts,
    mark_reply_sent,
    resolve_lid_to_phone,
    update_contact,
)

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


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


@router.post("/incoming")
async def whatsapp_incoming(payload: IncomingMessagePayload):
    """Receive an incoming WhatsApp message from the Baileys service."""
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
    """Receive a Baileys LID-to-phone mapping and update the contact row."""
    contact = resolve_lid_to_phone(payload.lid, payload.phone, payload.jid)
    logger.info(
        f"WHATSAPP_LID_RESOLVED lid={payload.lid} phone={payload.phone} "
        f"contact_id={getattr(contact, 'id', None)}"
    )
    return {"status": "ok", "contact_id": getattr(contact, "id", None)}


@router.get("/contacts")
def whatsapp_contacts(limit: int = 200):
    """Return all WhatsApp acquisition contacts for the dashboard."""
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
    """Manually add a WhatsApp contact (bypasses state machine, marked PHONE_ACQUIRED)."""
    phone = payload.phone.strip().lstrip("+").replace(" ", "")
    if not phone:
        raise HTTPException(status_code=400, detail="phone is required")
    contact = create_manual_contact(phone, payload.name, payload.property_address)
    return {"status": "ok", "id": contact.id}


@router.patch("/contacts/{contact_id}")
def whatsapp_edit_contact(contact_id: int, payload: EditContactPayload):
    """Edit an unresolved (lid) contact — update phone, name, and/or property address."""
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


# ── Background reply dispatcher ───────────────────────────────────────────────

async def _dispatch_due_replies():
    """Send all due WhatsApp replies (reply_scheduled_at <= NOW)."""
    contacts = await asyncio.to_thread(get_due_contacts)
    sent = 0

    for contact in contacts:
        reply = getattr(contact, "last_ai_reply", None)
        if not reply:
            # Nothing to send — just clear the schedule
            await asyncio.to_thread(mark_reply_sent, contact.id)
            continue

        ok = await asyncio.to_thread(send_whatsapp_message, contact.phone_number, reply)
        if ok:
            await asyncio.to_thread(mark_reply_sent, contact.id)
            sent += 1
            logger.info(
                f"WHATSAPP_REPLY_DISPATCHED phone={contact.phone_number} "
                f"status={contact.status}"
            )
        else:
            # Back-off: reschedule 5 minutes later
            from datetime import timedelta
            new_time = datetime.utcnow() + timedelta(minutes=5)
            await asyncio.to_thread(
                update_contact,
                contact.id,
                reply_scheduled_at=new_time,
            )
            logger.warning(
                f"WHATSAPP_REPLY_SEND_FAILED phone={contact.phone_number} "
                "rescheduled +5m"
            )

    if sent:
        logger.info(f"WHATSAPP_DISPATCH_CYCLE sent={sent}")

    return sent


async def whatsapp_reply_dispatcher_loop():
    while True:
        try:
            await _dispatch_due_replies()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"WHATSAPP_DISPATCH_CYCLE_FAILED error={exc}")
        await asyncio.sleep(30)


def start_whatsapp_reply_dispatcher():
    logger.info("WHATSAPP_REPLY_DISPATCHER_STARTED interval_seconds=30")
    return asyncio.create_task(
        whatsapp_reply_dispatcher_loop(),
        name="whatsapp-reply-dispatcher",
    )


async def stop_whatsapp_reply_dispatcher(task):
    if not task:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
