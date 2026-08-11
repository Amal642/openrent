"""
Repair: conversations that reached a terminal stage but still show
status=AI_FAILED because the status column lagged the conversation_stage.

This mirrors the in-pipeline sync in scripts/process_replies.py (which sets
status = conversation_stage for these stages) — but that sync only fires when a
thread is re-processed (i.e. the landlord replies again). Dead/completed threads
are never re-processed, so their stale AI_FAILED status lingers and inflates the
dashboard's "Needs attention" count. This script fixes that backlog directly.

Only DEFINITIVE/terminal stages are reclassified. VIEWING_BOOKED and in-progress
stages (VIEWING_DISCUSSION, VIEWING_PENDING, NEW_LEAD, CONTACT_REQUESTED) are
intentionally left as AI_FAILED — those threads may still be active and warrant
a human look, so we don't hide them.

Run from project root:
    python scripts/fix_ai_failed_status.py --dry-run   # preview, no changes
    python scripts/fix_ai_failed_status.py             # apply
"""
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.connection import SessionLocal
from app.db.models import Conversation

# Matches the auto-sync set in process_replies.py (HANDOFF_COMPLETE,
# VIEWING_CANCELLED, SHORT_TERM_PROPERTY) — terminal outcomes only.
TARGET_STAGES = {"HANDOFF_COMPLETE", "VIEWING_CANCELLED", "SHORT_TERM_PROPERTY"}


def main(dry_run: bool = False):
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
            print("Nothing to fix — no AI_FAILED rows with a terminal stage found.")
            return

        prefix = "[DRY-RUN] would update" if dry_run else "Updating"
        print(f"{prefix} {len(rows)} rows (status AI_FAILED -> conversation_stage):")
        for stage, n in Counter(c.conversation_stage for c in rows).most_common():
            print(f"  {stage}: {n}")

        if dry_run:
            print("Dry-run only — no changes committed.")
            return

        for c in rows:
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
    main(dry_run="--dry-run" in sys.argv)
