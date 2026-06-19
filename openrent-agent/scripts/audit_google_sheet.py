import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.integrations.google_sheets import (
    GoogleSheetsConfigurationError,
    GoogleSheetsLeadExporter,
    MONTH_NAMES,
    build_sheets_service,
)


def main():
    if not settings.GOOGLE_SHEET_ID:
        raise GoogleSheetsConfigurationError("GOOGLE_SHEET_ID is required")

    exporter = GoogleSheetsLeadExporter(
        build_sheets_service(),
        settings.GOOGLE_SHEET_ID,
        person=settings.GOOGLE_SHEET_PERSON or "Becky",
        template_tab=settings.GOOGLE_SHEET_TEMPLATE_TAB,
    )
    report = exporter.audit()
    print(json.dumps(report, indent=2, default=str))

    invalid = [
        tab
        for tab in report["tabs"]
        if not tab["header_ok"]
        and (
            tab["title"] in MONTH_NAMES
            or tab["title"] == settings.GOOGLE_SHEET_TEMPLATE_TAB
        )
    ]
    if invalid:
        print(
            f"Audit completed with {len(invalid)} incompatible tab(s).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
