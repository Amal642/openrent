import argparse
import json

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
