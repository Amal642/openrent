import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import settings
from app.integrations.google_sheets import (
    GoogleSheetsConfigurationError,
    GoogleSheetsLeadExporter,
    build_sheets_service,
)


def main():
    if not settings.GOOGLE_SHEET_ID:
        raise GoogleSheetsConfigurationError("GOOGLE_SHEET_ID is required")

    exporter = GoogleSheetsLeadExporter(
        build_sheets_service(),
        settings.GOOGLE_SHEET_ID,
        person=settings.GOOGLE_SHEET_PERSON or "Becky",
        destination_tab=settings.GOOGLE_SHEET_TAB or "Becky",
    )
    report = exporter.audit()
    print(json.dumps(report, indent=2, default=str))

    destination_tab = settings.GOOGLE_SHEET_TAB or "Becky"
    destination = next(
        (tab for tab in report["tabs"] if tab["title"] == destination_tab),
        None,
    )
    if not destination:
        print(
            f"Audit failed: destination tab {destination_tab!r} does not exist.",
            file=sys.stderr,
        )
        return 1
    if not destination["header_ok"]:
        print(
            f"Audit failed: destination tab {destination_tab!r} has incompatible headers.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
