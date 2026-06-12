"""
One-time repair: conversations that completed (HANDOFF_COMPLETE or VIEWING_CANCELLED)
but still show status=AI_FAILED because the old code never called update_conversation_status
after cancellation/handoff.

Run from the project root:
    python scripts/fix_ai_failed_status.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import SessionLocal
from app.db.models import Conversation

TARGET_STAGES = {"HANDOFF_COMPLETE", "VIEWING_CANCELLED"}


def main():
    db = SessionLocal()
    try:
        rows = (
            db.query(Conversation)
            .filter(
                Conversation.status == "AI_FAILED",
                Conversation.conversation_stage.in_(TARGET_STAGES),
            )
            .all()
        )

        if not rows:
            print("Nothing to fix — no AI_FAILED rows with completed stage found.")
            return

        print(f"Found {len(rows)} rows to fix:")
        for c in rows:
            print(f"  thread_id={c.thread_id}  stage={c.conversation_stage}  -> status={c.conversation_stage}")
            c.status = c.conversation_stage

        db.commit()
        print(f"Done. {len(rows)} rows updated.")

    except Exception as exc:
        db.rollback()
        print(f"Error: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
