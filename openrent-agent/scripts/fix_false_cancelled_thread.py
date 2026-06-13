"""
One-time repair for threads incorrectly marked as VIEWING_CANCELLED
due to a false-positive banner detection (the viewing was never actually
confirmed or was an informal agreement the bot misread).

What this script does:
  - Resets conversation_stage to NULL so the bot picks it up again
  - Clears viewing_confirmed and viewing_cancelled flags
  - Clears handoff_completed_at so the handoff gate doesn't block it
  - Sets status to SKIPPED so the dashboard shows it's waiting

Run from the project root:
    python scripts/fix_false_cancelled_thread.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import SessionLocal
from app.db.models import Conversation

# Thread IDs to unlock (add more if needed)
TARGET_THREAD_IDS = ["44364105"]


def main():
    db = SessionLocal()
    try:
        rows = (
            db.query(Conversation)
            .filter(Conversation.thread_id.in_(TARGET_THREAD_IDS))
            .all()
        )

        if not rows:
            print("No matching threads found.")
            return

        print(f"Found {len(rows)} thread(s) to fix:")
        for c in rows:
            print(
                f"  thread_id={c.thread_id} "
                f"stage={c.conversation_stage!r} "
                f"status={c.status!r} "
                f"viewing_confirmed={c.viewing_confirmed} "
                f"viewing_cancelled={c.viewing_cancelled}"
            )
            c.conversation_stage = None
            c.status = "SKIPPED"
            c.viewing_confirmed = False
            c.viewing_cancelled = False
            c.handoff_completed_at = None

        db.commit()
        print(f"\nDone. {len(rows)} thread(s) unlocked — bot will pick them up on the next run.")

    except Exception as exc:
        db.rollback()
        print(f"Error: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
