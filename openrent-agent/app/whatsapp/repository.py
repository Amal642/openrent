"""
DB access functions for whatsapp_contacts table.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.db.connection import SessionLocal
from app.db.models import Conversation, Listing, WhatsAppContact


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
            # Attempt to fetch linked property address
            property_address = None
            if c.listing_id:
                listing = db.query(Listing).filter(Listing.id == c.listing_id).first()
                if listing:
                    property_address = listing.property_address

            result.append({
                "id": c.id,
                "phone_number": c.phone_number,
                "name": c.name,
                "landlord_id": c.landlord_id,
                "listing_id": c.listing_id,
                "property_address": property_address,
                "thread_id": c.thread_id,
                "first_message": c.first_message,
                "last_message": c.last_message,
                "last_received_at": c.last_received_at.isoformat() if c.last_received_at else None,
                "status": c.status,
                "confidence": c.confidence,
                "reply_scheduled_at": c.reply_scheduled_at.isoformat() if c.reply_scheduled_at else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            })
        return result
    finally:
        db.close()
