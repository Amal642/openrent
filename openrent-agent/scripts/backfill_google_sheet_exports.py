import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.init_db import init_db
from app.db.repository import backfill_sheet_export_outbox


def main():
    parser = argparse.ArgumentParser(
        description="Create Google Sheets outbox records for existing phone leads."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create records. Without this flag the command is read-only.",
    )
    args = parser.parse_args()

    init_db()
    result = backfill_sheet_export_outbox(dry_run=not args.apply)
    result["mode"] = "apply" if args.apply else "dry-run"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
