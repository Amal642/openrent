"""
One-off backfill: re-run matching for WhatsApp contacts already closed out as
SAVED_UNMATCHED, using evidence already captured on the contact (no LLM
re-extraction). Intended to be run once after loosening the match threshold
or fixing the matcher scoring logic, to unstick contacts that should have
matched under the corrected logic.

Capture-only: updates CRM match fields (and flips status to PHONE_ACQUIRED
on a fresh match via apply_match_result) but never sends a WhatsApp message.
"""
from __future__ import annotations

import json

from app.db.connection import SessionLocal
from app.db.models import WhatsAppContact
from app.whatsapp.handler import _match_status
from app.whatsapp.matcher import match_by_evidence
from app.whatsapp.repository import apply_match_result


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


def main() -> None:
    db = SessionLocal()
    try:
        contacts = db.query(WhatsAppContact).filter(
            WhatsAppContact.status == "SAVED_UNMATCHED"
        ).all()
    finally:
        db.close()

    print(f"Found {len(contacts)} SAVED_UNMATCHED contact(s) to re-evaluate.")

    unstuck = 0
    for contact in contacts:
        names = _dedupe(
            [contact.name] + [n for n in _json_list(contact.extracted_names) if isinstance(n, str)]
        )
        property_hints = _dedupe(
            [p for p in _json_list(contact.property_hints) if isinstance(p, str)]
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

        if match_status == "MATCHED":
            unstuck += 1

        print(
            f"{contact.id}\t{contact.phone_number}\t{contact.name!r}\t"
            f"{match_status}\tconfidence={confidence:.1f}\t"
            f"{best.get('property_address') if best else ''}"
        )

    print(f"\nDone. {unstuck}/{len(contacts)} contact(s) newly matched -> PHONE_ACQUIRED.")


if __name__ == "__main__":
    main()
