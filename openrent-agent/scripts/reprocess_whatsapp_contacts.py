"""
Re-run WhatsApp evidence extraction and matching for existing contacts.

This is intentionally capture-only: it updates CRM match fields but does not
schedule or send WhatsApp replies.
"""
from __future__ import annotations

import json
from datetime import datetime

from app.db.connection import SessionLocal
from app.db.models import WhatsAppContact
from app.whatsapp.matcher import (
    extract_name_from_message,
    extract_property_from_message,
    match_by_evidence,
)
from app.whatsapp.repository import (
    apply_match_result,
    update_contact,
)

PARTIAL_MATCH_THRESHOLD = 65.0
AUTO_MATCH_THRESHOLD = 85.0
AUTO_MATCH_MIN_GAP = 5.0


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


def _messages_for(contact: WhatsAppContact) -> list[str]:
    messages = []
    for event in _json_list(contact.message_history):
        if isinstance(event, dict) and event.get("message"):
            messages.append(event["message"])
    if contact.first_message:
        messages.append(contact.first_message)
    if contact.last_message:
        messages.append(contact.last_message)
    return _dedupe(messages)


def _match_status(candidates: list[dict], confidence: float) -> str:
    if not candidates:
        return "UNMATCHED"
    second = float(candidates[1].get("confidence") or 0) if len(candidates) > 1 else 0.0
    has_clear_gap = len(candidates) == 1 or confidence - second >= AUTO_MATCH_MIN_GAP
    if confidence >= AUTO_MATCH_THRESHOLD and has_clear_gap:
        return "MATCHED"
    if confidence >= PARTIAL_MATCH_THRESHOLD:
        return "PARTIAL_MATCH"
    return "UNMATCHED"


def main() -> None:
    db = SessionLocal()
    try:
        contacts = db.query(WhatsAppContact).all()
    finally:
        db.close()

    for contact in contacts:
        names = [contact.name]
        property_hints = []
        messages = _messages_for(contact)

        for message in messages:
            name = extract_name_from_message(message)
            if name:
                names.append(name)
            property_hint = extract_property_from_message(message)
            if property_hint:
                property_hints.append(property_hint)

        names = _dedupe(names)
        property_hints = _dedupe(property_hints)

        contact = update_contact(
            contact.id,
            name=names[0] if names else contact.name,
            extracted_names=json.dumps(names, ensure_ascii=False),
            property_hints=json.dumps(property_hints, ensure_ascii=False),
        ) or contact

        if not contact.message_history and messages:
            update_contact(
                contact.id,
                message_history=json.dumps(
                    [
                        {
                            "direction": "inbound",
                            "message": message,
                            "received_at": (
                                contact.last_received_at or datetime.utcnow()
                            ).isoformat(),
                            "sender_name": contact.name,
                            "jid": contact.jid,
                            "lid": contact.lid,
                            "message_id": None,
                        }
                        for message in messages
                    ],
                    ensure_ascii=False,
                ),
            )

        candidates, confidence = match_by_evidence(names, property_hints)
        best = candidates[0] if candidates else None
        match_status = _match_status(candidates, confidence)
        apply_match_result(
            contact.id,
            candidates=candidates,
            best=best,
            confidence=confidence,
            match_status=match_status,
        )
        print(
            f"{contact.id}\t{contact.phone_number}\t{match_status}\t"
            f"{confidence:.1f}\t{best.get('property_address') if best else ''}"
        )


if __name__ == "__main__":
    main()
