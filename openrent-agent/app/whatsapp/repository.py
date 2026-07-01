"""
DB access functions for whatsapp_contacts table.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from app.db.connection import SessionLocal
from app.db.models import Conversation, Listing, WhatsAppContact


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _append_unique(existing: list[str], values: list[str]) -> list[str]:
    seen = {item.strip().lower() for item in existing if isinstance(item, str)}
    result = list(existing)
    for value in values:
        cleaned = (value or "").strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
    return result


def _message_event(
    *,
    direction: str,
    message: str,
    received_at: datetime,
    sender_name: str | None = None,
    jid: str | None = None,
    lid: str | None = None,
    message_id: str | None = None,
) -> dict:
    return {
        "direction": direction,
        "message": message,
        "received_at": received_at.isoformat(),
        "sender_name": sender_name,
        "jid": jid,
        "lid": lid,
        "message_id": message_id,
    }


def get_contact_by_phone(phone: str) -> Optional[WhatsAppContact]:
    db = SessionLocal()
    try:
        return (
            db.query(WhatsAppContact)
            .filter(WhatsAppContact.phone_number == phone)
            .first()
        )
    finally:
        db.close()


def get_contact_by_lid(lid: str) -> Optional[WhatsAppContact]:
    db = SessionLocal()
    try:
        return (
            db.query(WhatsAppContact)
            .filter(WhatsAppContact.lid == lid)
            .first()
        )
    finally:
        db.close()


def get_or_create_contact(phone: str, first_message: str) -> WhatsAppContact:
    db = SessionLocal()
    try:
        contact = (
            db.query(WhatsAppContact)
            .filter(WhatsAppContact.phone_number == phone)
            .first()
        )
        if not contact:
            contact = WhatsAppContact(
                phone_number=phone,
                first_message=first_message,
                last_message=first_message,
                last_received_at=datetime.utcnow(),
                status="NEW_CONTACT",
            )
            db.add(contact)
            db.commit()
            db.refresh(contact)
        return contact
    finally:
        db.close()


def capture_incoming_message(
    *,
    phone: str,
    message: str,
    received_at: datetime,
    sender_name: str | None = None,
    jid: str | None = None,
    lid: str | None = None,
    message_id: str | None = None,
) -> WhatsAppContact:
    """Create/update a WhatsApp contact and append the inbound message history."""
    db = SessionLocal()
    try:
        contact = (
            db.query(WhatsAppContact)
            .filter(WhatsAppContact.phone_number == phone)
            .first()
        )
        if not contact and lid:
            contact = (
                db.query(WhatsAppContact)
                .filter(WhatsAppContact.lid == lid)
                .first()
            )

        if not contact:
            contact = WhatsAppContact(
                phone_number=phone,
                lid=lid,
                jid=jid,
                name=sender_name,
                first_message=message,
                last_message=message,
                last_received_at=received_at,
                status="NEW_CONTACT",
                match_status="UNMATCHED",
                created_at=received_at,
            )
            db.add(contact)
            db.flush()
        else:
            if lid and not contact.lid:
                contact.lid = lid
            if jid:
                contact.jid = jid
            if sender_name and not contact.name:
                contact.name = sender_name
            if not contact.first_message:
                contact.first_message = message

        history = _json_list(contact.message_history)
        if message_id and any(
            item.get("message_id") == message_id
            for item in history
            if isinstance(item, dict)
        ):
            # Duplicate webhook; still refresh last-seen metadata below.
            pass
        else:
            history.append(
                _message_event(
                    direction="inbound",
                    message=message,
                    received_at=received_at,
                    sender_name=sender_name,
                    jid=jid,
                    lid=lid,
                    message_id=message_id,
                )
            )
            contact.message_history = _json_dumps(history)

        contact.last_message = message
        contact.last_received_at = received_at
        contact.last_message_id = message_id
        contact.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(contact)
        return contact
    finally:
        db.close()


def update_contact_evidence(
    contact_id: int,
    *,
    names: list[str] | None = None,
    property_hints: list[str] | None = None,
) -> Optional[WhatsAppContact]:
    db = SessionLocal()
    try:
        contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == contact_id).first()
        if not contact:
            return None

        if names:
            existing = _json_list(contact.extracted_names)
            contact.extracted_names = _json_dumps(_append_unique(existing, names))
            if not contact.name:
                contact.name = names[0].strip()

        if property_hints:
            existing = _json_list(contact.property_hints)
            contact.property_hints = _json_dumps(_append_unique(existing, property_hints))

        contact.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(contact)
        return contact
    finally:
        db.close()


def apply_match_result(
    contact_id: int,
    *,
    candidates: list[dict],
    best: dict | None,
    confidence: float,
    match_status: str,
) -> Optional[WhatsAppContact]:
    db = SessionLocal()
    try:
        contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == contact_id).first()
        if not contact:
            return None

        contact.match_candidates = _json_dumps(candidates[:5])
        contact.match_status = match_status
        contact.confidence = confidence or None

        if best and match_status == "MATCHED":
            contact.listing_id = best.get("listing_id")
            contact.landlord_id = best.get("landlord_id")
            contact.thread_id = best.get("thread_id")
            contact.status = "PHONE_ACQUIRED"

            conversation = None
            if best.get("thread_id"):
                conversation = (
                    db.query(Conversation)
                    .filter(Conversation.thread_id == best.get("thread_id"))
                    .first()
                )
            if not conversation and best.get("listing_id"):
                conversation = (
                    db.query(Conversation)
                    .filter(Conversation.listing_id == best.get("listing_id"))
                    .first()
                )
            if conversation:
                conversation.extracted_phone = contact.phone_number
                conversation.phone_found = True
                conversation.phone_found_at = datetime.utcnow()
                conversation.status = "PHONE_ACQUIRED"
        elif contact.status in {None, "NEW_CONTACT"}:
            contact.status = "AWAITING_PROPERTY"

        contact.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(contact)
        return contact
    finally:
        db.close()


def resolve_lid_to_phone(lid: str, phone: str, jid: str | None = None) -> Optional[WhatsAppContact]:
    """Replace or merge an unresolved lid:* row with the real phone number.

    Baileys v7 can emit PN<->LID mappings for contacts that never sent an
    inbound lead message. Those mappings should not create empty CRM contacts;
    they should only resolve rows we already captured from /incoming.
    """
    db = SessionLocal()
    try:
        lid_value = lid.replace("@lid", "").replace("lid:", "")
        unresolved_phone = f"lid:{lid_value}"
        source = (
            db.query(WhatsAppContact)
            .filter(
                (WhatsAppContact.lid == lid_value)
                | (WhatsAppContact.phone_number == unresolved_phone)
            )
            .first()
        )
        target = (
            db.query(WhatsAppContact)
            .filter(WhatsAppContact.phone_number == phone)
            .first()
        )

        if source and target and source.id != target.id:
            for attr in [
                "name",
                "first_message",
                "last_message",
                "last_received_at",
                "status",
                "listing_id",
                "landlord_id",
                "thread_id",
                "confidence",
                "match_status",
            ]:
                if getattr(source, attr, None) and not getattr(target, attr, None):
                    setattr(target, attr, getattr(source, attr))
            for attr in ["message_history", "extracted_names", "property_hints", "match_candidates"]:
                if getattr(source, attr, None) and not getattr(target, attr, None):
                    setattr(target, attr, getattr(source, attr))
            target.lid = target.lid or lid_value
            target.jid = jid or target.jid
            target.reply_scheduled_at = None
            target.updated_at = datetime.utcnow()
            db.delete(source)
            db.commit()
            db.refresh(target)
            return target

        contact = source or target
        if not contact:
            return None
        else:
            contact.phone_number = phone
            contact.lid = contact.lid or lid_value
            contact.jid = jid or contact.jid
            contact.reply_scheduled_at = None
            contact.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(contact)
        return contact
    finally:
        db.close()


def create_manual_contact(phone: str, name: Optional[str], property_address: Optional[str]) -> WhatsAppContact:
    """Create a manually-entered contact, marked as PHONE_ACQUIRED with no confidence score."""
    db = SessionLocal()
    try:
        existing = db.query(WhatsAppContact).filter(WhatsAppContact.phone_number == phone).first()
        if existing:
            if name:
                existing.name = name
            if property_address:
                existing.property_address = property_address
            existing.is_manual = True
            existing.status = "PHONE_ACQUIRED"
            existing.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(existing)
            return existing

        contact = WhatsAppContact(
            phone_number=phone,
            name=name,
            property_address=property_address,
            status="PHONE_ACQUIRED",
            is_manual=True,
            match_status="UNMATCHED",
            created_at=datetime.utcnow(),
        )
        db.add(contact)
        db.commit()
        db.refresh(contact)
        return contact
    finally:
        db.close()


def update_contact(contact_id: int, **kwargs) -> Optional[WhatsAppContact]:
    db = SessionLocal()
    try:
        contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == contact_id).first()
        if not contact:
            return None
        for key, value in kwargs.items():
            setattr(contact, key, value)
        contact.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(contact)
        return contact
    finally:
        db.close()


def get_due_contacts() -> list[WhatsAppContact]:
    """Return contacts with a pending reply due now (reply_scheduled_at <= NOW and not PHONE_ACQUIRED)."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        return (
            db.query(WhatsAppContact)
            .filter(
                WhatsAppContact.reply_scheduled_at <= now,
                WhatsAppContact.reply_scheduled_at.isnot(None),
                WhatsAppContact.status != "PHONE_ACQUIRED",
            )
            .all()
        )
    finally:
        db.close()


def get_contacts_due_for_cancellation() -> list[WhatsAppContact]:
    """
    Return contacts linked to conversations where a viewing was cancelled
    and a WhatsApp cancellation message hasn't been sent yet.

    Matches via thread_id OR listing_id (union, deduplicated).
    Triggers:
      - conversation_stage='VIEWING_BOOKED' AND cancel_required=True
      - conversation_stage='VIEWING_CANCELLED'
    """
    from sqlalchemy import or_, and_
    db = SessionLocal()
    try:
        cancellation_condition = or_(
            and_(
                Conversation.conversation_stage == "VIEWING_BOOKED",
                Conversation.cancel_required == True,
            ),
            Conversation.conversation_stage == "VIEWING_CANCELLED",
        )

        thread_ids = set(
            row[0]
            for row in db.query(WhatsAppContact.id)
            .join(Conversation, WhatsAppContact.thread_id == Conversation.thread_id)
            .filter(
                cancellation_condition,
                WhatsAppContact.cancellation_sent_at.is_(None),
                WhatsAppContact.status != "CANCELLED",
                WhatsAppContact.thread_id.isnot(None),
            )
            .all()
        )

        listing_ids = set(
            row[0]
            for row in db.query(WhatsAppContact.id)
            .join(Conversation, WhatsAppContact.listing_id == Conversation.listing_id)
            .filter(
                cancellation_condition,
                WhatsAppContact.cancellation_sent_at.is_(None),
                WhatsAppContact.status != "CANCELLED",
                WhatsAppContact.listing_id.isnot(None),
            )
            .all()
        )

        all_ids = thread_ids | listing_ids
        if not all_ids:
            return []
        return db.query(WhatsAppContact).filter(WhatsAppContact.id.in_(all_ids)).all()
    finally:
        db.close()


def mark_contact_cancelled(contact_id: int) -> None:
    """Set contact status to CANCELLED and record cancellation_sent_at."""
    db = SessionLocal()
    try:
        contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == contact_id).first()
        if contact:
            contact.status = "CANCELLED"
            contact.cancellation_sent_at = datetime.utcnow()
            contact.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def mark_reply_sent(contact_id: int) -> None:
    db = SessionLocal()
    try:
        contact = db.query(WhatsAppContact).filter(WhatsAppContact.id == contact_id).first()
        if contact:
            contact.reply_scheduled_at = None
            contact.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def link_conversation(contact: WhatsAppContact, landlord_name: str) -> bool:
    """
    Try to find a matching conversation via listings.landlord_name and update
    conversation.extracted_phone / phone_found / phone_found_at / status.
    Returns True if a match was found and updated.
    """
    db = SessionLocal()
    try:
        # Find listings matching the landlord name (case-insensitive, partial)
        listings = (
            db.query(Listing)
            .filter(
                Listing.landlord_name.ilike(f"%{landlord_name}%")
            )
            .all()
        )
        if not listings:
            return False

        # Get the first conversation linked to any of those listings
        for listing in listings:
            conv = (
                db.query(Conversation)
                .filter(Conversation.listing_id == listing.id)
                .first()
            )
            if conv:
                conv.extracted_phone = contact.phone_number
                conv.phone_found = True
                conv.phone_found_at = datetime.utcnow()
                conv.status = "PHONE_ACQUIRED"
                db.commit()
                return True

        return False
    finally:
        db.close()


def get_all_contacts(limit: int = 200) -> list[dict]:
    """Return all contacts as dicts for API responses."""
    db = SessionLocal()
    try:
        contacts = (
            db.query(WhatsAppContact)
            .order_by(WhatsAppContact.last_received_at.desc())
            .limit(limit)
            .all()
        )
        result = []
        for c in contacts:
            # Property address: from linked listing, or direct column (manual entries)
            property_address = getattr(c, "property_address", None)
            if c.listing_id:
                listing = db.query(Listing).filter(Listing.id == c.listing_id).first()
                if listing and listing.property_address:
                    property_address = listing.property_address

            result.append({
                "id": c.id,
                "phone_number": c.phone_number,
                "lid": c.lid,
                "jid": c.jid,
                "name": c.name,
                "landlord_id": c.landlord_id,
                "listing_id": c.listing_id,
                "property_address": property_address,
                "thread_id": c.thread_id,
                "first_message": c.first_message,
                "last_message": c.last_message,
                "message_history": _json_list(c.message_history),
                "extracted_names": _json_list(c.extracted_names),
                "property_hints": _json_list(c.property_hints),
                "match_status": c.match_status,
                "match_candidates": _json_list(c.match_candidates),
                "last_received_at": c.last_received_at.isoformat() if c.last_received_at else None,
                "status": c.status,
                "confidence": c.confidence,
                "is_manual": bool(getattr(c, "is_manual", False)),
                "reply_scheduled_at": c.reply_scheduled_at.isoformat() if c.reply_scheduled_at else None,
                "cancellation_sent_at": c.cancellation_sent_at.isoformat() if c.cancellation_sent_at else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            })
        return result
    finally:
        db.close()
