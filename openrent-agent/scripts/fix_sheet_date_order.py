"""
Fix gap-fill rows in the Becky Google Sheet.

Gap-fills occur when the slot-finding algorithm filled an empty slot with a newer lead,
causing a later date to appear before earlier dates.

For each identified gap-fill row:
  1. Clear the row from the sheet (so _find_existing_row won't find it as existing)
  2. Reset the DB export record to PENDING so the dispatcher re-exports it to the end
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.init_db import init_db
from app.db.models import LeadSheetExport, Conversation
from app.db.repository import session_scope
from app.integrations.google_sheets import (
    build_sheets_service,
    configured_exporter,
    quote_sheet_name,
    validate_enabled_config,
)
from app.config import settings


DESTINATION_TAB = "Becky"
GAP_THRESHOLD_DAYS = 1


def find_gap_fills(db):
    rows = (
        db.query(LeadSheetExport, Conversation)
        .join(Conversation, LeadSheetExport.conversation_id == Conversation.id)
        .filter(
            LeadSheetExport.destination_tab == DESTINATION_TAB,
            LeadSheetExport.destination_row != None,
            LeadSheetExport.status == "EXPORTED",
        )
        .order_by(LeadSheetExport.destination_row)
        .all()
    )

    ordered = [
        (exp.destination_row, conv.phone_found_at, exp.id)
        for exp, conv in rows
    ]

    gap_fills = []
    for i in range(len(ordered) - 1):
        row, ts, eid = ordered[i]
        _, next_ts, _ = ordered[i + 1]
        if ts - next_ts > timedelta(days=GAP_THRESHOLD_DAYS):
            gap_fills.append({
                "export_id": eid,
                "sheet_row": row,
                "date": ts.date().isoformat(),
                "days_ahead": (ts - next_ts).days,
            })

    return gap_fills


def clear_sheet_row(service, spreadsheet_id, tab_name, row_number):
    range_str = f"{quote_sheet_name(tab_name)}!A{row_number}:L{row_number}"
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=range_str,
    ).execute()


def reset_export_to_pending(db, export_id):
    export = db.query(LeadSheetExport).filter(LeadSheetExport.id == export_id).one()
    export.status = "PENDING"
    export.destination_row = None
    export.destination_tab = None
    export.attempt_count = 0
    export.next_attempt_at = datetime.utcnow()
    export.error_message = None
    db.flush()


def main():
    parser = argparse.ArgumentParser(description="Fix out-of-order gap-fill rows in the Becky sheet.")
    parser.add_argument("--apply", action="store_true", help="Apply fixes. Without this flag, dry-run only.")
    args = parser.parse_args()

    validate_enabled_config()
    init_db()

    with session_scope() as db:
        gap_fills = find_gap_fills(db)

    print(f"Found {len(gap_fills)} gap-fill rows")
    print(json.dumps(gap_fills, indent=2))

    if not gap_fills:
        print("Nothing to fix.")
        return

    if not args.apply:
        print("\nDry-run complete. Pass --apply to fix.")
        return

    service = build_sheets_service()
    spreadsheet_id = settings.GOOGLE_SHEET_ID

    with session_scope() as db:
        for item in gap_fills:
            export_id = item["export_id"]
            row = item["sheet_row"]
            print(f"  Clearing sheet row {row} (export_id={export_id}, date={item['date']}, days_ahead={item['days_ahead']}) ...")
            clear_sheet_row(service, spreadsheet_id, DESTINATION_TAB, row)
            reset_export_to_pending(db, export_id)
            print(f"    -> cleared and reset to PENDING")
        db.commit()

    print(f"\nDone. {len(gap_fills)} exports reset to PENDING. The dispatcher will re-export them to the end of the sheet.")


if __name__ == "__main__":
    main()
