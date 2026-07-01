"""
Main entry point for incoming WhatsApp messages.

Phase 1 behavior:
  - capture every inbound message into whatsapp_contacts.message_history
  - accumulate names and property hints across messages
  - match against existing listings by name and/or property
  - write confirmed matches back to CRM conversations

Automatic replies are still controlled by WHATSAPP_AUTO_REPLY_ENABLED.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Optional

from app.config import settings
from app.utils.logger import logger
from app.whatsapp.matcher import (
    extract_name_from_message,
    extract_property_from_message,
    match_by_evidence,
)
from app.whatsapp.reply import (
    build_name_ask,
    build_property_ask,
    generate_closing_reply,
    next_reply_time,
)
from app.whatsapp.repository import (
    apply_match_result,
    capture_incoming_message,
    get_contact_by_phone,
    update_contact,
    update_contact_evidence,
)

PARTIAL_MATCH_THRESHOLD = 65.0
AUTO_MATCH_THRESHOLD = 85.0
AUTO_MATCH_MIN_GAP = 5.0


def _normalize_phone(raw: str) -> str:
    """Strip non-digits. Ensure starts with country code (default 44 for UK)."""
    if raw.startswith("lid:"):
        return raw
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return raw
    if digits.startswith("0"):
        digits = "44" + digits[1:]
    return digits


def _json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _dedupe(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = (value or "").strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
    return result


def _lid_from_phone_or_jid(phone: str, jid: str | None, lid: str | None) -> str | None:
    if lid:
        return lid.replace("@lid", "").replace("lid:", "")
    if jid and jid.endswith("@lid"):
        return jid.replace("@lid", "")
    if phone.startswith("lid:"):
        return phone[4:]
    return None


def _received_at(timestamp: Optional[int]) -> datetime:
    if not timestamp:
        return datetime.utcnow()
    try:
        return datetime.utcfromtimestamp(int(timestamp))
    except Exception:
        return datetime.utcnow()


def _schedule_reply(contact_id: int, message: str, next_status: str, **extra_updates) -> None:
    """Store or suppress the pending reply depending on the feature flag."""
    if not settings.WHATSAPP_AUTO_REPLY_ENABLED:
        update_contact(
            contact_id,
            status=next_status,
            reply_scheduled_at=None,
            last_ai_reply=None,
            **extra_updates,
        )
        logger.info(
            f"WHATSAPP_REPLY_CAPTURE_ONLY contact_id={contact_id} "
            f"next_status={next_status}"
        )
        return

    update_contact(
        contact_id,
        status=next_status,
        reply_scheduled_at=next_reply_time(),
        last_ai_reply=message,
        **extra_updates,
    )


def _match_status(candidates: list[dict], confidence: float) -> str:
    if not candidates:
        return "UNMATCHED"

    second_confidence = (
        float(candidates[1].get("confidence") or 0)
        if len(candidates) > 1
        else 0.0
    )
    has_clear_gap = len(candidates) == 1 or confidence - second_confidence >= AUTO_MATCH_MIN_GAP

    if confidence >= AUTO_MATCH_THRESHOLD and has_clear_gap:
        return "MATCHED"
    if confidence >= PARTIAL_MATCH_THRESHOLD:
        return "PARTIAL_MATCH"
    return "UNMATCHED"


async def handle_incoming_message(
    phone_number: str,
    message: str,
    timestamp: Optional[int] = None,
    sender_name: Optional[str] = None,
    jid: Optional[str] = None,
    lid: Optional[str] = None,
    message_id: Optional[str] = None,
) -> None:
    """
    Main entry point called by the FastAPI webhook.
    sender_name is WhatsApp pushName/profile display name when available.
    """
    phone = _normalize_phone(phone_number)
    received_at = _received_at(timestamp)
    lid_value = _lid_from_phone_or_jid(phone, jid, lid)

    logger.info(
        f"WHATSAPP_INCOMING phone={phone} lid={lid_value} "
        f"sender_name={sender_name!r} message_len={len(message)}"
    )

    # Guard: never interact with cancelled contacts
    _existing = get_contact_by_phone(phone)
    if _existing and getattr(_existing, "status", None) == "CANCELLED":
        logger.info(f"WHATSAPP_INCOMING_BLOCKED_CANCELLED phone={phone}")
        return

    contact = capture_incoming_message(
        phone=phone,
        message=message,
        received_at=received_at,
        sender_name=sender_name,
        jid=jid,
        lid=lid_value,
        message_id=message_id,
    )

    new_names: list[str] = []
    if sender_name:
        new_names.append(sender_name)

    extracted_name = extract_name_from_message(message)
    if extracted_name:
        new_names.append(extracted_name)

    new_property_hints: list[str] = []
    property_hint = extract_property_from_message(message)
    if property_hint:
        new_property_hints.append(property_hint)

    contact = (
        update_contact_evidence(
            contact.id,
            names=_dedupe(new_names),
            property_hints=_dedupe(new_property_hints),
        )
        or contact
    )

    all_names = _dedupe(
        [contact.name]
        + [item for item in _json_list(contact.extracted_names) if isinstance(item, str)]
        + new_names
    )
    all_property_hints = _dedupe(
        [item for item in _json_list(contact.property_hints) if isinstance(item, str)]
        + new_property_hints
    )

    candidates, confidence = match_by_evidence(all_names, all_property_hints)
    best = candidates[0] if candidates else None
    match_status = _match_status(candidates, confidence)

    contact = (
        apply_match_result(
            contact.id,
            candidates=candidates,
            best=best,
            confidence=confidence,
            match_status=match_status,
        )
        or contact
    )

    logger.info(
        f"WHATSAPP_MATCH_EVALUATED phone={phone} status={match_status} "
        f"confidence={confidence:.1f} names={all_names!r} properties={all_property_hints!r}"
    )

    display_name = contact.name or (all_names[0] if all_names else None)
    if match_status == "MATCHED" and best:
        _schedule_reply(
            contact.id,
            generate_closing_reply(display_name),
            "PHONE_ACQUIRED",
            listing_id=best.get("listing_id"),
            landlord_id=best.get("landlord_id"),
            thread_id=best.get("thread_id"),
            confidence=confidence,
        )
        return

    if all_names or all_property_hints:
        _schedule_reply(
            contact.id,
            build_property_ask(display_name),
            "AWAITING_PROPERTY",
            name=display_name,
            confidence=confidence or None,
        )
        return

    _schedule_reply(contact.id, build_name_ask(), "AWAITING_NAME")
