"""
One-shot migration: add cancellation_sent_at to whatsapp_contacts.

Run from openrent-agent/:
    python scripts/add_whatsapp_cancellation_column.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db.connection import SessionLocal
from sqlalchemy import text


def main():
    db = SessionLocal()
    try:
        # Check if column already exists
        result = db.execute(text("PRAGMA table_info(whatsapp_contacts)"))
        columns = [row[1] for row in result.fetchall()]
        if "cancellation_sent_at" in columns:
            print("Column cancellation_sent_at already exists — nothing to do.")
            return
        db.execute(
            text("ALTER TABLE whatsapp_contacts ADD COLUMN cancellation_sent_at DATETIME")
        )
        db.commit()
        print("Added cancellation_sent_at to whatsapp_contacts.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
