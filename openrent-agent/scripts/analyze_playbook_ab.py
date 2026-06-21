"""Report OPEN-21D phone captures from the production database.

The append-only outcome log is diagnostic. The authoritative capture event is
conversations.phone_found_at, and only captures at or after assignment count.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.repository import get_playbook_ab_database_outcomes  # noqa: E402
from app.experiments import playbook_ab  # noqa: E402


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assignments",
        type=Path,
        default=Path("logs/playbook_ab_assignments.jsonl"),
    )
    parser.add_argument(
        "--include-legacy",
        action="store_true",
        help="Include assignments created before eligibility metadata was added.",
    )
    args = parser.parse_args()

    assignments = _read_jsonl(args.assignments)
    outcomes = get_playbook_ab_database_outcomes(
        assignment["lead_id"] for assignment in assignments
    )
    report = playbook_ab.summarize_database_captures(
        assignments,
        outcomes,
        include_legacy=args.include_legacy,
    )
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
