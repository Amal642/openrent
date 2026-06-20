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
    parser.add_argument(
        "--location",
        help=(
            "Case-insensitive search-profile location filter, for example "
            "'London'. Omit to inspect all locations."
        ),
    )
    parser.add_argument(
        "--expected-count",
        type=int,
        help=(
            "Safety check for apply mode. Abort unless the number of leads "
            "that would be created or requeued exactly matches this value."
        ),
    )
    parser.add_argument(
        "--requeue-existing",
        action="store_true",
        help=(
            "Also reset already-tracked matching exports to PENDING. Use this "
            "to update existing sheet rows after changing mapped values."
        ),
    )
    args = parser.parse_args()

    init_db()
    if args.apply and args.expected_count is not None:
        preview = backfill_sheet_export_outbox(
            dry_run=True,
            location=args.location,
            requeue_existing=args.requeue_existing,
        )
        if preview["actionable"] != args.expected_count:
            parser.error(
                "Actionable lead count changed: "
                f"expected {args.expected_count}, found {preview['actionable']}. "
                "Run the dry-run preview again."
            )

    result = backfill_sheet_export_outbox(
        dry_run=not args.apply,
        location=args.location,
        requeue_existing=args.requeue_existing,
    )
    result["mode"] = "apply" if args.apply else "dry-run"
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
