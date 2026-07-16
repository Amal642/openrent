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
    append_outbound_message,
    capture_incoming_message,
    get_contact_by_phone,
    get_conversation_for_contact,
    outbound_message_count,
    outbound_message_exists,
    update_contact,
    update_contact_evidence,
)

PARTIAL_MATCH_THRESHOLD = 65.0
AUTO_MATCH_THRESHOLD = 85.0
AUTO_MATCH_MIN_GAP = 5.0

# Goal on this channel is narrow: landlord's number (implicit, it's WhatsApp),
# name, and property. Never chase property details past this many dedicated asks.
MAX_PROPERTY_ASKS = 2
MAX_AUTOMATED_REPLIES = 3
TERMINAL_REGULAR_REPLY_STATUSES = {
    "PHONE_ACQUIRED",
    "SAVED_UNMATCHED",
    "MAX_REPLIES_REACHED",
}

_SUSPICIOUS_PATTERNS = (
    r"\bwho are you\b",
    r"\bwho is this\b",
    r"\bprove\b",
    r"\bscam\b",
    r"\bfraud\b",
    r"\bfake\b",
    r"\bnot real\b",
    r"\bbot\b",
    r"\bautomat(ed|ic|ion)\b",
    r"\bare you (a |an )?(ai|robot)\b",
    r"\bis this (a |an )?(bot|ai|automated)\b",
    r"\breport(ing|ed)?\b.{0,15}\b(you|this number)\b",
    r"\bstop (messaging|texting|contacting) me\b",
    r"\bharass",
)
_SUSPICIOUS_RE = re.compile("|".join(_SUSPICIOUS_PATTERNS), re.IGNORECASE)


def _is_suspicious_message(message: str) -> bool:
    return bool(_SUSPICIOUS_RE.search(message or ""))


_VIEWING_KEYWORDS = (
    "viewing",
    "view the property",
    "view the flat",
    "view the house",
    "see the property",
    "see the flat",
    "see the place",
    "still on for",
    "still happening",
    "still good for",
    "appointment",
    "confirm the time",
    "confirm the viewing",
)


def _mentions_viewing(message: str) -> bool:
    text = message.lower()
    return any(keyword in text for keyword in _VIEWING_KEYWORDS)


async def _send_viewing_cancellation(contact, conversation) -> None:
    """Reactively cancel when the landlord brings up the viewing themselves,
    on top of the existing scheduled (time-based) cancellation dispatch."""
    from app.ai.replies import generate_cancellation_message
    from app.db.repository import mark_viewing_cancelled, save_message
    from app.whatsapp.browser_worker import get_worker
    from app.whatsapp.repository import get_contact_messages_for_ai, mark_contact_cancelled

    history = get_contact_messages_for_ai(contact)
    msg, error = generate_cancellation_message(history)
    if not msg or error:
        logger.warning(
            f"WHATSAPP_REACTIVE_CANCEL_AI_FAILED phone={contact.phone_number} error={error}"
        )
        return

    ok = await get_worker().send_message(contact.phone_number, msg)
    if not ok:
        logger.warning(
            f"WHATSAPP_REACTIVE_CANCEL_SEND_FAILED phone={contact.phone_number} "
            "reason=send failed, scheduled dispatch will retry"
        )
        return

    append_outbound_message(contact.id, msg)
    mark_contact_cancelled(contact.id)
    if conversation.thread_id:
        save_message(conversation.thread_id, "outbound", msg)
        mark_viewing_cancelled(conversation.thread_id)
    logger.info(
        f"WHATSAPP_REACTIVE_CANCEL_SENT phone={contact.phone_number} contact_id={contact.id}"
    )


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
    if outbound_message_exists(contact_id, message):
        update_contact(
            contact_id,
            status="MAX_REPLIES_REACHED",
            reply_scheduled_at=None,
            last_ai_reply=None,
            **extra_updates,
        )
        logger.warning(
            f"WHATSAPP_REPLY_SUPPRESSED_DUPLICATE_TEXT contact_id={contact_id}"
        )
        return

    sent_count = outbound_message_count(contact_id)
    if sent_count >= MAX_AUTOMATED_REPLIES:
        update_contact(
            contact_id,
            status="MAX_REPLIES_REACHED",
            reply_scheduled_at=None,
            last_ai_reply=None,
            **extra_updates,
        )
        logger.info(
            f"WHATSAPP_REPLY_SUPPRESSED_MAX_REPLIES contact_id={contact_id} "
            f"sent_count={sent_count} max={MAX_AUTOMATED_REPLIES}"
        )
        return

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


def _save_unmatched_and_close(
    contact,
    display_name: Optional[str],
    property_hint: Optional[str],
    confidence: float,
) -> None:
    """No confident CRM match, and we're not going to keep asking or ask the
    landlord to confirm — just persist whatever we extracted and close out."""
    update_contact(
        contact.id,
        name=display_name or contact.name,
        property_address=property_hint or contact.property_address,
    )
    _schedule_reply(
        contact.id,
        generate_closing_reply(display_name),
        "SAVED_UNMATCHED",
        confidence=confidence or None,
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

    # Guard: never interact with cancelled or suspicion-flagged contacts.
    # Suspicion requires manual review to clear before automation resumes.
    _existing = get_contact_by_phone(phone)
    if _existing and getattr(_existing, "status", None) == "CANCELLED":
        logger.info(f"WHATSAPP_INCOMING_BLOCKED_CANCELLED phone={phone}")
        return
    if _existing and getattr(_existing, "status", None) == "SUSPICIOUS_HOLD":
        logger.info(f"WHATSAPP_INCOMING_BLOCKED_SUSPICIOUS phone={phone}")
        return

    # Guard: a retried/redelivered inbound message must never trigger a second
    # reply — this is the root cause of a landlord getting the same message twice.
    is_duplicate_delivery = bool(
        message_id and _existing and _existing.last_message_id == message_id
    )

    contact = capture_incoming_message(
        phone=phone,
        message=message,
        received_at=received_at,
        sender_name=sender_name,
        jid=jid,
        lid=lid_value,
        message_id=message_id,
    )

    if is_duplicate_delivery:
        logger.info(
            f"WHATSAPP_DUPLICATE_MESSAGE_IGNORED phone={phone} message_id={message_id}"
        )
        return

    if _is_suspicious_message(message):
        update_contact(
            contact.id,
            status="SUSPICIOUS_HOLD",
            reply_scheduled_at=None,
            last_ai_reply=None,
        )
        logger.warning(
            f"WHATSAPP_SUSPICION_DETECTED phone={phone} contact_id={contact.id} "
            "reason=message matched suspicious pattern, halting automation"
        )
        return

    if _mentions_viewing(message):
        conversation = get_conversation_for_contact(contact)
        if conversation:
            cancellation_due = (
                conversation.conversation_stage == "VIEWING_CANCELLED"
                or (
                    conversation.conversation_stage == "VIEWING_BOOKED"
                    and conversation.cancel_required
                )
            )
            if (
                cancellation_due
                and not contact.cancellation_sent_at
                and contact.status != "CANCELLED"
            ):
                await _send_viewing_cancellation(contact, conversation)
                return

    if contact.status in TERMINAL_REGULAR_REPLY_STATUSES:
        logger.info(
            f"WHATSAPP_INCOMING_NO_REGULAR_REPLY phone={phone} status={contact.status}"
        )
        return

    sent_count = outbound_message_count(contact.id)
    if sent_count >= MAX_AUTOMATED_REPLIES:
        update_contact(
            contact.id,
            status="MAX_REPLIES_REACHED",
            reply_scheduled_at=None,
            last_ai_reply=None,
        )
        logger.info(
            f"WHATSAPP_INCOMING_MAX_REPLIES_REACHED phone={phone} "
            f"sent_count={sent_count} max={MAX_AUTOMATED_REPLIES}"
        )
        return

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

    history = _json_list(contact.message_history)

    if all_names and all_property_hints:
        # We have both pieces of info already — don't chase a higher-confidence
        # CRM match and don't ask the landlord to confirm, just save it and close.
        _save_unmatched_and_close(contact, display_name, all_property_hints[0], confidence)
        return

    if contact.status == "SAVED_UNMATCHED":
        # Already gave up asking and closed this contact out; don't reopen it.
        return

    if all_names or all_property_hints:
        if (contact.property_ask_count or 0) >= MAX_PROPERTY_ASKS:
            # Asked twice for the property and the landlord hasn't given a
            # usable one (e.g. deflects with "today is the viewing") — leave
            # it rather than keep pushing. Save whatever we have and close.
            property_hint = all_property_hints[0] if all_property_hints else None
            _save_unmatched_and_close(contact, display_name, property_hint, confidence)
            return

        _schedule_reply(
            contact.id,
            build_property_ask(display_name, history),
            "AWAITING_PROPERTY",
            name=display_name,
            confidence=confidence or None,
            property_ask_count=(contact.property_ask_count or 0) + 1,
        )
        return

    _schedule_reply(
        contact.id,
        build_property_ask(display_name, history),
        "AWAITING_PROPERTY",
        name=display_name,
        property_ask_count=(contact.property_ask_count or 0) + 1,
    )
