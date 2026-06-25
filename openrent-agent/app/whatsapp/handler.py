"""
Main entry point for incoming WhatsApp messages.
Implements the state machine:
  NEW_CONTACT -> AWAITING_NAME | AWAITING_PROPERTY | PHONE_ACQUIRED
  AWAITING_NAME -> AWAITING_PROPERTY | PHONE_ACQUIRED
  AWAITING_PROPERTY -> PHONE_ACQUIRED (or ask again once)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from app.utils.logger import logger
from app.whatsapp.matcher import (
    AUTO_LINK_THRESHOLD,
    extract_name_from_message,
    extract_property_from_message,
    get_all_match_candidates,
    match_landlord_by_name,
)
from app.whatsapp.reply import (
    build_name_ask,
    build_property_ask,
    generate_closing_reply,
    next_reply_time,
    send_whatsapp_message,
)
from app.whatsapp.repository import (
    get_or_create_contact,
    link_conversation,
    mark_reply_sent,
    update_contact,
)


def _normalize_phone(raw: str) -> str:
    """Strip non-digits. Ensure starts with country code (default 44 for UK)."""
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return raw
    # If starts with 0, replace with 44
    if digits.startswith("0"):
        digits = "44" + digits[1:]
    return digits


def _acquire_phone(contact_id: int, phone: str, name: Optional[str], listing_id: Optional[int], landlord_id: Optional[int], confidence: float) -> None:
    """Mark contact as PHONE_ACQUIRED and link to conversation."""
    # Try to link to existing conversation before status update
    if name:
        from app.db.models import WhatsAppContact as _WAC
        _dummy = _WAC()
        _dummy.phone_number = phone
        _dummy.id = contact_id
        linked = link_conversation(_dummy, name)
        if linked:
            logger.info(f"WHATSAPP_CONVERSATION_LINKED phone={phone} name={name}")


def _schedule_reply(contact_id: int, message: str, next_status: str, **extra_updates) -> None:
    """Store the pending reply message and schedule it."""
    update_contact(
        contact_id,
        status=next_status,
        reply_scheduled_at=next_reply_time(),
        last_ai_reply=message,
        **extra_updates,
    )


async def handle_incoming_message(
    phone_number: str,
    message: str,
    timestamp: Optional[int] = None,
    sender_name: Optional[str] = None,
) -> None:
    """
    Main entry point called by the FastAPI webhook.
    Runs the state machine and schedules a reply.
    sender_name: WhatsApp display name from msg.pushName (most reliable source).
    """
    phone = _normalize_phone(phone_number)
    logger.info(f"WHATSAPP_INCOMING phone={phone} sender_name={sender_name!r} message_len={len(message)}")

    # Get or create contact record
    contact = get_or_create_contact(phone, message)

    # Always update last message
    update_contact(
        contact.id,
        last_message=message,
        last_received_at=datetime.utcnow(),
    )

    # Ignore already-acquired contacts
    if contact.status == "PHONE_ACQUIRED":
        logger.info(f"WHATSAPP_IGNORED_ALREADY_ACQUIRED phone={phone}")
        return

    current_status = contact.status or "NEW_CONTACT"
    name = contact.name  # may already be known from a previous message

    # If WhatsApp gave us the contact's display name and we don't have it yet, store it
    if sender_name and not name:
        name = sender_name
        update_contact(contact.id, name=name)
        logger.info(f"WHATSAPP_NAME_FROM_PUSHNAME phone={phone} name={name!r}")

    # ── NEW_CONTACT ─────────────────────────────────────────────────────────────
    if current_status == "NEW_CONTACT":
        # Use pushName if available, otherwise extract from message text
        extracted_name = name or extract_name_from_message(message)

        if not extracted_name:
            # No name — ask who they are
            _schedule_reply(
                contact.id,
                build_name_ask(),
                "AWAITING_NAME",
            )
            logger.info(f"WHATSAPP_STATE new_contact->awaiting_name phone={phone}")
            return

        name = extracted_name
        update_contact(contact.id, name=name)

        # Try to match by name
        candidates, confidence = get_all_match_candidates(name, None)
        unique = [c for c in candidates if c["confidence"] >= AUTO_LINK_THRESHOLD]

        if len(unique) == 1:
            best = unique[0]
            _acquire_phone(
                contact.id, phone, name,
                best["listing_id"], best["landlord_id"], best["confidence"]
            )
            closing = generate_closing_reply(name)
            _schedule_reply(contact.id, closing, "PHONE_ACQUIRED",
                            listing_id=best["listing_id"], landlord_id=best["landlord_id"],
                            confidence=best["confidence"])
            logger.info(f"WHATSAPP_STATE new_contact->phone_acquired phone={phone} confidence={best['confidence']:.1f}")
        elif len(unique) > 1:
            # Multiple matches — ask for property
            _schedule_reply(
                contact.id,
                build_property_ask(name),
                "AWAITING_PROPERTY",
                name=name,
            )
            logger.info(f"WHATSAPP_STATE new_contact->awaiting_property (multiple) phone={phone}")
        else:
            # No confident match — ask for property
            _schedule_reply(
                contact.id,
                build_property_ask(name),
                "AWAITING_PROPERTY",
                name=name,
            )
            logger.info(f"WHATSAPP_STATE new_contact->awaiting_property (no_match) phone={phone}")

    # ── AWAITING_NAME ────────────────────────────────────────────────────────────
    elif current_status == "AWAITING_NAME":
        # Treat entire message as the name
        name = message.strip()
        update_contact(contact.id, name=name)

        candidates, confidence = get_all_match_candidates(name, None)
        unique = [c for c in candidates if c["confidence"] >= AUTO_LINK_THRESHOLD]

        if len(unique) == 1:
            best = unique[0]
            closing = generate_closing_reply(name)
            _acquire_phone(contact.id, phone, name, best["listing_id"], best["landlord_id"], best["confidence"])
            _schedule_reply(contact.id, closing, "PHONE_ACQUIRED",
                            listing_id=best["listing_id"], landlord_id=best["landlord_id"],
                            confidence=best["confidence"])
            logger.info(f"WHATSAPP_STATE awaiting_name->phone_acquired phone={phone}")
        else:
            _schedule_reply(
                contact.id,
                build_property_ask(name),
                "AWAITING_PROPERTY",
                name=name,
            )
            logger.info(f"WHATSAPP_STATE awaiting_name->awaiting_property phone={phone}")

    # ── AWAITING_PROPERTY ────────────────────────────────────────────────────────
    elif current_status == "AWAITING_PROPERTY":
        property_hint = extract_property_from_message(message)
        candidates, confidence = get_all_match_candidates(name, property_hint)

        if confidence >= 85.0 and candidates:
            best = candidates[0]
            closing = generate_closing_reply(name)
            _acquire_phone(contact.id, phone, name, best["listing_id"], best["landlord_id"], confidence)
            _schedule_reply(contact.id, closing, "PHONE_ACQUIRED",
                            listing_id=best["listing_id"], landlord_id=best["landlord_id"],
                            confidence=confidence)
            logger.info(f"WHATSAPP_STATE awaiting_property->phone_acquired phone={phone} confidence={confidence:.1f}")
        else:
            # Low confidence — one more attempt with a clarification ask
            clarification = (
                "I'm sorry, I just want to make sure I have the right property! "
                "Could you give me a little more detail — perhaps the full address or postcode?"
            )
            # Move to a terminal "asked_twice" state to avoid looping — store as AWAITING_PROPERTY
            # but clear reply_scheduled_at after this send (handled by dispatcher)
            _schedule_reply(
                contact.id,
                clarification,
                "AWAITING_PROPERTY",
            )
            logger.info(f"WHATSAPP_STATE awaiting_property->awaiting_property (low_confidence={confidence:.1f}) phone={phone}")
