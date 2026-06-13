"""
Diagnose why total_phones count is stuck.

Run from project root:
    python scripts/diagnose_phone_count.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import SessionLocal
from app.db.models import Conversation

db = SessionLocal()
try:
    dup_count = db.query(Conversation).filter(Conversation.status == "DUPLICATE_LEAD").count()
    unique_phones = (
        db.query(Conversation.extracted_phone)
        .filter(Conversation.extracted_phone != None)
        .distinct()
        .count()
    )
    total_with_phone = (
        db.query(Conversation)
        .filter(Conversation.extracted_phone != None)
        .count()
    )
    recent = (
        db.query(Conversation.extracted_phone, Conversation.phone_found_at, Conversation.thread_id)
        .filter(Conversation.extracted_phone != None)
        .order_by(Conversation.phone_found_at.desc())
        .limit(10)
        .all()
    )

    print(f"DUPLICATE_LEAD threads:   {dup_count}")
    print(f"Unique phones in DB:      {unique_phones}")
    print(f"Conversations with phone: {total_with_phone}  (>unique means same number saved on 2+ threads)")
    print()
    print("Most recent 10 phones captured:")
    for phone, found_at, tid in recent:
        print(f"  thread={tid}  phone={phone}  found_at={found_at}")
finally:
    db.close()
