import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.init_db import init_db
from app.db.repository import get_sheet_metadata_backfill_candidates
from app.jobs.sync_google_sheets import METADATA_FIELDS, _hydrate_missing_metadata
from app.utils.logger import logger


def _read_listing_ids(path):
    return [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _public_candidate(candidate):
    missing_fields = [
        field
        for field in METADATA_FIELDS
        if candidate.get(field) is None
    ]
    return {
        "export_id": candidate["export_id"],
        "listing_id": candidate["listing_id"],
        "thread_id": candidate["thread_id"],
        "search_location": candidate["search_location"],
        "missing_fields": missing_fields,
        "action": "hydrate" if missing_fields else "skip_complete",
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Hydrate persisted listing metadata for an explicit, already-exported "
            "phone-lead allowlist. The command never scans or updates other leads."
        )
    )
    parser.add_argument(
        "--listing-id-file",
        required=True,
        help="Text file containing one allowed OpenRent listing ID per line.",
    )
    parser.add_argument(
        "--location",
        required=True,
        help="Required case-insensitive search-profile location guard.",
    )
    parser.add_argument(
        "--expected-count",
        required=True,
        type=int,
        help="Abort unless the allowlist and matched production records have this count.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Fetch and save metadata. Without this flag the command is read-only.",
    )
    args = parser.parse_args()

    listing_ids = _read_listing_ids(args.listing_id_file)
    unique_listing_ids = list(dict.fromkeys(listing_ids))
    if len(listing_ids) != len(unique_listing_ids):
        parser.error("The listing allowlist contains duplicate IDs.")
    if len(unique_listing_ids) != args.expected_count:
        parser.error(
            "Allowlist count changed: "
            f"expected {args.expected_count}, found {len(unique_listing_ids)}."
        )

    init_db()
    selection = get_sheet_metadata_backfill_candidates(
        unique_listing_ids,
        location=args.location,
    )
    if selection["missing_listing_ids"]:
        parser.error(
            "Some allowlisted IDs are not tracked phone leads in the required location: "
            + ", ".join(selection["missing_listing_ids"])
        )
    if len(selection["candidates"]) != args.expected_count:
        parser.error(
            "Matched production record count changed: "
            f"expected {args.expected_count}, found {len(selection['candidates'])}."
        )

    candidates = selection["candidates"]
    public_candidates = [_public_candidate(candidate) for candidate in candidates]
    needs_hydration = [
        candidate
        for candidate in candidates
        if any(candidate.get(field) is None for field in METADATA_FIELDS)
    ]
    result = {
        "mode": "apply" if args.apply else "dry-run",
        "location_guard": args.location,
        "allowlisted": len(unique_listing_ids),
        "matched": len(candidates),
        "needs_hydration": len(needs_hydration),
        "already_complete": len(candidates) - len(needs_hydration),
        "succeeded": 0,
        "failed": 0,
        "leads": public_candidates,
    }

    if args.apply:
        for candidate in needs_hydration:
            logger.info(
                "CRM_METADATA_BACKFILL_START "
                f"export_id={candidate['export_id']} "
                f"listing_id={candidate['listing_id']}"
            )
            try:
                _hydrate_missing_metadata(candidate)
                result["succeeded"] += 1
                logger.info(
                    "CRM_METADATA_BACKFILL_SUCCESS "
                    f"export_id={candidate['export_id']} "
                    f"listing_id={candidate['listing_id']}"
                )
            except Exception as exc:
                result["failed"] += 1
                logger.exception(
                    "CRM_METADATA_BACKFILL_FAILED "
                    f"export_id={candidate['export_id']} "
                    f"listing_id={candidate['listing_id']} "
                    f"error_type={type(exc).__name__}"
                )

    print(json.dumps(result, indent=2, default=str))
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
