from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.db.connection import SessionLocal
from app.db.models import WhatsAppContact


def _parse_ts(value: int | float | str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None)


def _group_messages(messages: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for msg in messages:
        phone = str(msg.get("phone") or "").strip()
        text = str(msg.get("message") or "").strip()
        if not phone or not text:
            continue
        grouped[phone].append(msg)
    for rows in grouped.values():
        rows.sort(key=lambda item: float(item.get("timestamp") or 0))
    return grouped


def import_history(path: Path, dry_run: bool) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    grouped = _group_messages(payload.get("messages") or [])

    db = SessionLocal()
    created = 0
    updated = 0
    unchanged = 0
    try:
        for phone, rows in grouped.items():
            first = rows[0]
            last = rows[-1]
            first_text = str(first.get("message") or "")
            last_text = str(last.get("message") or "")
            first_ts = _parse_ts(first.get("timestamp"))
            last_ts = _parse_ts(last.get("timestamp"))
            sender_name = last.get("sender_name") or first.get("sender_name")

            contact = (
                db.query(WhatsAppContact)
                .filter(WhatsAppContact.phone_number == phone)
                .first()
            )
            if not contact:
                created += 1
                contact = WhatsAppContact(
                    phone_number=phone,
                    name=sender_name,
                    first_message=first_text,
                    last_message=last_text,
                    last_received_at=last_ts,
                    status="NEW_CONTACT",
                    last_ai_reply=None,
                    reply_scheduled_at=None,
                    created_at=first_ts or datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                db.add(contact)
                continue

            changed = False
            if sender_name and not contact.name:
                contact.name = sender_name
                changed = True
            if first_ts and (
                not contact.created_at or first_ts < contact.created_at
            ):
                contact.first_message = first_text
                contact.created_at = first_ts
                changed = True
            if last_ts and (
                not contact.last_received_at or last_ts >= contact.last_received_at
            ):
                contact.last_message = last_text
                contact.last_received_at = last_ts
                changed = True

            # Recovery import must never schedule stale replies.
            if contact.reply_scheduled_at is not None or contact.last_ai_reply is not None:
                contact.reply_scheduled_at = None
                contact.last_ai_reply = None
                changed = True

            if changed:
                contact.updated_at = datetime.utcnow()
                updated += 1
            else:
                unchanged += 1

        if dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return {
        "contacts_seen": len(grouped),
        "messages_seen": sum(len(rows) for rows in grouped.values()),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()

    result = import_history(args.path, dry_run=not args.commit)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
