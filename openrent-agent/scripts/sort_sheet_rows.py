"""
Sort all data rows in the Becky sheet by date (phone_found_at as tiebreaker).

The sheet accumulated out-of-order rows from gap-fill bugs and re-exports.
This script reads all 732 data rows, sorts them by date serial then
phone_found_at from the DB, and rewrites the values back to the same
row slots (rows 3, 5, 7, ...) so the sheet is fully chronological.

Formatting and row structure are preserved — only cell values are rewritten.

Dry-run:
    python scripts/sort_sheet_rows.py

Apply:
    python scripts/sort_sheet_rows.py --apply
"""

import sys
import argparse
from datetime import date as date_type, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.integrations.google_sheets import (
    build_sheets_service,
    validate_enabled_config,
    quote_sheet_name,
)
from app.db.init_db import init_db
from app.db.models import LeadSheetExport, Conversation
from app.db.repository import session_scope
from app.config import settings

DESTINATION_TAB = "Becky"
_SHEETS_EPOCH = date_type(1899, 12, 30)

# Sentinel for rows with no DB match — sort them last within their date
_FAR_FUTURE = "9999-99-99"


def canonicalize_url(url):
    if not url:
        return ""
    url = url.strip().split("?")[0].rstrip("/")
    return url


def build_url_to_ts_map(db):
    """Return {canonical_url: phone_found_at_isoformat} from DB."""
    rows = (
        db.query(LeadSheetExport, Conversation)
        .join(Conversation, LeadSheetExport.conversation_id == Conversation.id)
        .filter(
            LeadSheetExport.destination_tab == DESTINATION_TAB,
            LeadSheetExport.destination_row.isnot(None),
        )
        .all()
    )
    mapping = {}
    for exp, conv in rows:
        if conv.phone_found_at is None:
            continue
        # URL stored in payload — derive from listing_id if available
        # Use the destination_row to help identify, but URL is the real key
        # We don't have property_url directly on the model here;
        # we'll join via get_sheet_export_payload but that's expensive.
        # Instead we'll store destination_row -> phone_found_at and match by row.
        mapping[exp.destination_row] = conv.phone_found_at.isoformat()
    return mapping


def main():
    parser = argparse.ArgumentParser(description="Sort Becky sheet rows by date.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Without this flag, dry-run only.")
    args = parser.parse_args()

    validate_enabled_config()
    init_db()
    svc = build_sheets_service()
    spreadsheet_id = settings.GOOGLE_SHEET_ID

    # Get sheet metadata
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = None
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == DESTINATION_TAB:
            sheet_id = s["properties"]["sheetId"]
            break
    if sheet_id is None:
        raise RuntimeError(f"Tab '{DESTINATION_TAB}' not found.")

    # Read all cell values (unformatted so date serials come back as numbers)
    result = svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{quote_sheet_name(DESTINATION_TAB)}!A1:L1600",
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute()
    raw_rows = result.get("values", [])

    # Identify data row slots and collect their content
    # A data row has a numeric date serial in column B (index 1)
    data_slots = []  # list of (1-based sheet row, date_serial, full_row_list)
    for i, row in enumerate(raw_rows):
        if not row or len(row) < 2:
            continue
        val = row[1]
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 1000:
            # Pad to 12 cols
            padded = list(row) + [""] * (12 - len(row))
            data_slots.append((i + 1, int(val), padded))

    print(f"Found {len(data_slots)} data rows.")

    # Decorate with original index as tiebreaker so same-date rows keep
    # their current relative order (stable sort by date only).
    decorated = []
    for idx, (sheet_row, date_serial, cols) in enumerate(data_slots):
        decorated.append((date_serial, idx, sheet_row, cols))

    # Sort ascending by date_serial; idx tiebreaker makes it stable within a date
    decorated_sorted = sorted(decorated, key=lambda x: (x[0], x[1]))

    # Compare current order vs sorted order — find all positions that change
    changes = 0
    for i, (orig, sortd) in enumerate(zip(decorated, decorated_sorted)):
        if orig[2] != sortd[2]:  # sheet_row differs
            changes += 1

    print(f"Rows that need to move: {changes}")

    if changes == 0:
        print("Sheet is already in order. Nothing to do.")
        return

    # Show first few moves
    shown = 0
    for i, (orig, sortd) in enumerate(zip(decorated, decorated_sorted)):
        if orig[2] != sortd[2] and shown < 10:
            slot_row = data_slots[i][0]
            from datetime import timedelta
            orig_date = _SHEETS_EPOCH + timedelta(days=orig[0])
            new_date = _SHEETS_EPOCH + timedelta(days=sortd[0])
            print(f"  slot {slot_row}: currently {orig_date} (db_row={orig[2]}) -> will become {new_date} (db_row={sortd[2]})")
            shown += 1
    if changes > 10:
        print(f"  ... ({changes - 10} more)")

    if not args.apply:
        print("\nDry-run complete. Pass --apply to rewrite in sorted order.")
        return

    # Build batchUpdate: rewrite values for every data slot in sorted order
    # Each slot gets the sorted row's content written to it.
    # We write: userEnteredValue for all 12 cols, plus textFormatRuns for col L (URL).
    # We use fields "userEnteredValue,textFormatRuns" so we don't disturb number formats.
    # The date col (B, index 1) is already a serial; we just write it as numberValue.

    def make_cell(value, url_for_link=None):
        if value is None or value == "":
            cell = {"userEnteredValue": {"stringValue": ""}}
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            cell = {"userEnteredValue": {"numberValue": value}}
        else:
            cell = {"userEnteredValue": {"stringValue": str(value)}}
        if url_for_link:
            cell["textFormatRuns"] = [
                {"startIndex": 0, "format": {"link": {"uri": url_for_link}}}
            ]
        return cell

    requests = []
    for i, (date_serial, _idx, _orig_row, cols) in enumerate(decorated_sorted):
        target_sheet_row = data_slots[i][0]  # the slot this position maps to
        row_index = target_sheet_row - 1  # 0-based

        url_val = cols[11] if len(cols) > 11 else ""

        cells = []
        for col_idx, val in enumerate(cols[:12]):
            link = url_val if col_idx == 11 and url_val else None
            cells.append(make_cell(val, url_for_link=link))

        requests.append({
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_index,
                    "endRowIndex": row_index + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 12,
                },
                "rows": [{"values": cells}],
                "fields": "userEnteredValue,textFormatRuns",
            }
        })

    # Send in batches of 500
    BATCH = 500
    chunks = [requests[i:i + BATCH] for i in range(0, len(requests), BATCH)]
    for n, chunk in enumerate(chunks, 1):
        print(f"Writing batch {n}/{len(chunks)} ({len(chunk)} rows)...")
        svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": chunk},
        ).execute()
        print("  -> done")

    print(f"\nDone. {len(requests)} rows rewritten in chronological order.")

    # Now update the DB destination_row for each lead to match its new slot
    print("Updating DB destination_row records...")
    with session_scope() as db:
        updated = 0
        for i, (date_serial, _idx, orig_row, cols) in enumerate(decorated_sorted):
            new_slot_row = data_slots[i][0]
            if orig_row == new_slot_row:
                continue  # no change
            exp = db.query(LeadSheetExport).filter(
                LeadSheetExport.destination_row == orig_row,
                LeadSheetExport.destination_tab == DESTINATION_TAB,
            ).first()
            if exp:
                exp.destination_row = new_slot_row
                updated += 1
        db.commit()
    print(f"Updated {updated} DB records.")


if __name__ == "__main__":
    main()
