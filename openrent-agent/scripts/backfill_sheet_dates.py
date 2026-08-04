"""
Convert every text-format date in the Becky sheet (column B) to a proper
Google Sheets serial number with DD/MM/YYYY date format.

Text dates were written as strings (e.g. "03/08/2026") by old code.
They appear left-aligned in the sheet with an apostrophe prefix, can't be
sorted, filtered, or used in date calculations.

This script reads all rows, identifies cells where column B is a dd/mm/yyyy
string, and patches them in one batched batchUpdate with the correct
numberValue + DATE format.

Run dry-run first:
    python scripts/backfill_sheet_dates.py

Apply:
    python scripts/backfill_sheet_dates.py --apply
"""

import sys
import argparse
from datetime import date as date_type
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.integrations.google_sheets import (
    build_sheets_service,
    validate_enabled_config,
    quote_sheet_name,
)
from app.config import settings

DESTINATION_TAB = "Becky"
_SHEETS_EPOCH = date_type(1899, 12, 30)


def date_to_serial(text):
    """Parse dd/mm/yyyy string to a Google Sheets serial integer. Returns None on failure."""
    try:
        parts = text.strip().split("/")
        if len(parts) != 3:
            return None
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        return (date_type(y, m, d) - _SHEETS_EPOCH).days
    except (ValueError, IndexError):
        return None


def main():
    parser = argparse.ArgumentParser(description="Backfill text dates in Becky sheet to serial numbers.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Without this, dry-run only.")
    args = parser.parse_args()

    validate_enabled_config()
    svc = build_sheets_service()
    spreadsheet_id = settings.GOOGLE_SHEET_ID

    # Get sheet metadata so we have the sheetId
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = None
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == DESTINATION_TAB:
            sheet_id = s["properties"]["sheetId"]
            break
    if sheet_id is None:
        raise RuntimeError(f"Tab '{DESTINATION_TAB}' not found in spreadsheet.")

    # Read column B as unformatted values so text dates come back as strings
    # and serial dates come back as numbers
    result = svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{quote_sheet_name(DESTINATION_TAB)}!B1:B2000",
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute()

    rows = result.get("values", [])

    to_fix = []  # list of (0-based row index, serial int)
    for i, row in enumerate(rows):
        if not row:
            continue
        val = row[0]
        if not isinstance(val, str):
            continue  # already a number or empty
        serial = date_to_serial(val)
        if serial is None:
            continue
        to_fix.append((i, serial))

    print(f"Found {len(to_fix)} text-date cells to convert.")
    if not to_fix:
        print("Nothing to do.")
        return

    # Show sample
    for i, serial in to_fix[:5]:
        print(f"  row {i + 1}: '{rows[i][0]}' -> serial {serial}")
    if len(to_fix) > 5:
        print(f"  ... ({len(to_fix) - 5} more)")

    if not args.apply:
        print("\nDry-run complete. Pass --apply to write changes.")
        return

    # Build batchUpdate requests: one per cell (value + format)
    # Google Sheets API limits: 1000 requests per batchUpdate; chunk if needed
    BATCH_SIZE = 400  # 2 requests per cell = 800 total per batch

    def make_requests(chunk):
        reqs = []
        for row_index, serial in chunk:
            reqs.append({
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_index,
                        "endRowIndex": row_index + 1,
                        "startColumnIndex": 1,
                        "endColumnIndex": 2,
                    },
                    "rows": [{"values": [{"userEnteredValue": {"numberValue": serial}}]}],
                    "fields": "userEnteredValue",
                }
            })
            reqs.append({
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_index,
                        "endRowIndex": row_index + 1,
                        "startColumnIndex": 1,
                        "endColumnIndex": 2,
                    },
                    "rows": [{"values": [{"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd/mm/yyyy"}}}]}],
                    "fields": "userEnteredFormat.numberFormat",
                }
            })
        return reqs

    chunks = [to_fix[i:i + BATCH_SIZE] for i in range(0, len(to_fix), BATCH_SIZE)]
    for n, chunk in enumerate(chunks, 1):
        print(f"Sending batch {n}/{len(chunks)} ({len(chunk)} cells)...")
        svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": make_requests(chunk)},
        ).execute()
        print(f"  -> done")

    print(f"\nDone. {len(to_fix)} cells converted from text to serial date.")


if __name__ == "__main__":
    main()
