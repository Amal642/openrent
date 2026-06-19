import calendar
import hashlib
import json
import os
import re
import secrets
from collections import Counter
from datetime import timezone

from app.config import settings
from app.utils.logger import logger
from app.utils.scheduling import UK_TZ


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
EXPECTED_HEADERS = {
    0: "Person",
    1: "Date",
    2: "Direction",
    3: "Name of Landlord",
    4: "Phone Number",
    5: "Address",
    6: "Specifics",
    7: "Rent amount",
    11: "OpenRent Links",
}
MONTH_NAMES = tuple(calendar.month_name[1:])


class GoogleSheetsConfigurationError(RuntimeError):
    pass


class GoogleSheetsStructureError(RuntimeError):
    pass


def quote_sheet_name(name):
    return "'" + str(name).replace("'", "''") + "'"


def canonicalize_url(url):
    value = str(url or "").strip()
    return value.rstrip("/")


def extract_listing_id(url):
    matches = re.findall(r"(?:^|/)(\d{5,})(?:[/?#]|$)", str(url or ""))
    return matches[-1] if matches else None


def payload_hash(payload):
    serialized = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_sheets_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GoogleSheetsConfigurationError(
            "Google Sheets dependencies are not installed"
        ) from exc

    credentials = None
    if settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        try:
            info = json.loads(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
        except json.JSONDecodeError as exc:
            raise GoogleSheetsConfigurationError(
                "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON"
            ) from exc
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=[SHEETS_SCOPE],
        )
    else:
        credential_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not credential_path:
            raise GoogleSheetsConfigurationError(
                "GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON is required"
            )
        if not os.path.isfile(credential_path):
            raise GoogleSheetsConfigurationError(
                f"Google credential file does not exist: {credential_path}"
            )
        credentials = service_account.Credentials.from_service_account_file(
            credential_path,
            scopes=[SHEETS_SCOPE],
        )

    return build(
        "sheets",
        "v4",
        credentials=credentials,
        cache_discovery=False,
    )


def validate_enabled_config():
    if not settings.GOOGLE_SHEETS_ENABLED:
        raise GoogleSheetsConfigurationError("Google Sheets export is disabled")
    if not settings.GOOGLE_SHEET_ID:
        raise GoogleSheetsConfigurationError("GOOGLE_SHEET_ID is required")


class GoogleSheetsLeadExporter:
    def __init__(
        self,
        service,
        spreadsheet_id,
        *,
        person="Becky",
        template_tab=None,
    ):
        self.service = service
        self.spreadsheet_id = spreadsheet_id
        self.person = person
        self.template_tab = template_tab

    def _spreadsheet_metadata(self):
        response = (
            self.service.spreadsheets()
            .get(
                spreadsheetId=self.spreadsheet_id,
                fields=(
                    "spreadsheetId,properties(title,timeZone),"
                    "sheets(properties(sheetId,title,index,"
                    "gridProperties(rowCount,columnCount)))"
                ),
            )
            .execute()
        )
        return response

    def _sheet_properties(self, metadata):
        return [sheet["properties"] for sheet in metadata.get("sheets", [])]

    def _get_values(self, tab_name, range_suffix="A:L"):
        response = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{quote_sheet_name(tab_name)}!{range_suffix}",
                valueRenderOption="FORMATTED_VALUE",
            )
            .execute()
        )
        return response.get("values", [])

    def _validate_headers(self, tab_name, values):
        header = values[0] if values else []
        errors = []
        for index, expected in EXPECTED_HEADERS.items():
            actual = str(header[index]).strip() if index < len(header) else ""
            if actual.casefold() != expected.casefold():
                errors.append(
                    f"column={index + 1} expected={expected!r} actual={actual!r}"
                )
        if errors:
            raise GoogleSheetsStructureError(
                f"Header mismatch in tab {tab_name!r}: " + "; ".join(errors)
            )

    @staticmethod
    def _row_value(row, index):
        return str(row[index]).strip() if index < len(row) and row[index] is not None else ""

    @classmethod
    def _occupied_rows(cls, values):
        occupied = []
        for row_number, row in enumerate(values[1:], start=2):
            significant = row[:8] + (row[11:12] if len(row) > 11 else [])
            if any(str(value).strip() for value in significant):
                occupied.append(row_number)
        return occupied

    @classmethod
    def _lead_rows(cls, values):
        rows = []
        for row_number, row in enumerate(values[1:], start=2):
            if any(
                cls._row_value(row, index)
                for index in (0, 1, 3, 4, 5, 6, 7, 11)
            ):
                rows.append(row_number)
        return rows

    @staticmethod
    def _infer_cadence(rows):
        differences = [
            later - earlier
            for earlier, later in zip(rows, rows[1:])
            if 1 <= later - earlier <= 10
        ]
        if not differences:
            return 2
        return Counter(differences).most_common(1)[0][0]

    def _find_existing_row(self, values, property_url, listing_id):
        canonical = canonicalize_url(property_url)
        for row_number, row in enumerate(values[1:], start=2):
            existing_url = self._row_value(row, 11)
            if not existing_url:
                continue
            if canonicalize_url(existing_url) == canonical:
                return row_number
            existing_listing_id = extract_listing_id(existing_url)
            if listing_id and existing_listing_id == str(listing_id):
                return row_number
        return None

    def _select_template(self, sheets, target_month):
        by_title = {sheet["title"]: sheet for sheet in sheets}
        if self.template_tab:
            template = by_title.get(self.template_tab)
            if not template:
                raise GoogleSheetsStructureError(
                    f"Configured template tab {self.template_tab!r} does not exist"
                )
            return template

        month_index = MONTH_NAMES.index(target_month)
        for offset in range(1, 13):
            candidate = MONTH_NAMES[(month_index - offset) % 12]
            if candidate in by_title:
                return by_title[candidate]

        monthly = [sheet for sheet in sheets if sheet["title"] in MONTH_NAMES]
        if monthly:
            return sorted(monthly, key=lambda item: item.get("index", 0))[-1]

        for sheet in sheets:
            values = self._get_values(sheet["title"], "A1:L5")
            try:
                self._validate_headers(sheet["title"], values)
            except GoogleSheetsStructureError:
                continue
            return sheet

        raise GoogleSheetsStructureError(
            "No monthly or header-compatible template tab was found"
        )

    @staticmethod
    def _new_sheet_id(existing_ids):
        while True:
            candidate = secrets.randbelow(2_000_000_000) + 1
            if candidate not in existing_ids:
                return candidate

    def _create_month_tab(self, sheets, target_month):
        template = self._select_template(sheets, target_month)
        template_values = self._get_values(template["title"])
        self._validate_headers(template["title"], template_values)
        lead_rows = self._lead_rows(template_values)
        first_data_row = lead_rows[0] if lead_rows else 3
        cadence = self._infer_cadence(lead_rows)

        existing_ids = {sheet["sheetId"] for sheet in sheets}
        new_sheet_id = self._new_sheet_id(existing_ids)
        row_count = template.get("gridProperties", {}).get("rowCount", 1000)

        logger.info(
            "GOOGLE_SHEETS_MONTH_CREATE_START "
            f"spreadsheet_id={self.spreadsheet_id} target_tab={target_month} "
            f"template_tab={template['title']} template_sheet_id={template['sheetId']} "
            f"new_sheet_id={new_sheet_id} first_data_row={first_data_row} cadence={cadence}"
        )

        body = {
            "requests": [
                {
                    "duplicateSheet": {
                        "sourceSheetId": template["sheetId"],
                        "insertSheetIndex": len(sheets),
                        "newSheetId": new_sheet_id,
                        "newSheetName": target_month,
                    }
                },
                {
                    "updateCells": {
                        "range": {
                            "sheetId": new_sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": row_count,
                            "startColumnIndex": 0,
                            "endColumnIndex": 12,
                        },
                        "rows": [],
                        "fields": "userEnteredValue,textFormatRuns",
                    }
                },
            ]
        }
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body=body,
        ).execute()

        logger.info(
            "GOOGLE_SHEETS_MONTH_CREATE_SUCCESS "
            f"spreadsheet_id={self.spreadsheet_id} target_tab={target_month} "
            f"new_sheet_id={new_sheet_id}"
        )
        return {
            "sheetId": new_sheet_id,
            "title": target_month,
            "index": len(sheets),
            "gridProperties": dict(template.get("gridProperties", {})),
        }, first_data_row, cadence

    def _ensure_month_tab(self, target_month):
        metadata = self._spreadsheet_metadata()
        sheets = self._sheet_properties(metadata)
        for sheet in sheets:
            if sheet["title"] == target_month:
                values = self._get_values(target_month)
                self._validate_headers(target_month, values)
                lead_rows = self._lead_rows(values)
                return (
                    sheet,
                    values,
                    lead_rows[0] if lead_rows else 3,
                    self._infer_cadence(lead_rows),
                    False,
                )

        sheet, first_data_row, cadence = self._create_month_tab(sheets, target_month)
        values = self._get_values(target_month)
        self._validate_headers(target_month, values)
        return sheet, values, first_data_row, cadence, True

    @staticmethod
    def _cell(value, *, link=None):
        if value is None:
            value = ""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            cell = {"userEnteredValue": {"numberValue": value}}
        else:
            cell = {"userEnteredValue": {"stringValue": str(value)}}
        if link:
            cell["textFormatRuns"] = [
                {
                    "startIndex": 0,
                    "format": {"link": {"uri": link}},
                }
            ]
        return cell

    def _build_row(self, payload, event_date):
        bedrooms = payload.get("bedrooms")
        bathrooms = payload.get("bathrooms")
        specifics = (
            f"{bedrooms if bedrooms is not None else 'N/A'} bed "
            f"{bathrooms if bathrooms is not None else 'N/A'} bath"
        )
        url = canonicalize_url(payload["property_url"])
        values = [
            self.person,
            event_date.strftime("%d/%m/%Y"),
            "",
            payload.get("landlord_name") or "",
            payload.get("phone_number") or "",
            payload.get("address") or "",
            specifics,
            payload.get("rent_pcm"),
            "",
            "",
            "",
            url,
        ]
        cells = [
            self._cell(value, link=url if index == 11 and url else None)
            for index, value in enumerate(values)
        ]
        return values, cells

    def _write_row(
        self,
        *,
        sheet,
        values,
        target_row,
        source_format_row,
        cells,
    ):
        sheet_id = sheet["sheetId"]
        row_count = sheet.get("gridProperties", {}).get("rowCount", 1000)
        requests = []

        if target_row > row_count:
            requests.append(
                {
                    "appendDimension": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "length": max(100, target_row - row_count),
                    }
                }
            )

        if source_format_row and source_format_row != target_row:
            source = {
                "sheetId": sheet_id,
                "startRowIndex": source_format_row - 1,
                "endRowIndex": source_format_row,
                "startColumnIndex": 0,
                "endColumnIndex": 12,
            }
            destination = {
                "sheetId": sheet_id,
                "startRowIndex": target_row - 1,
                "endRowIndex": target_row,
                "startColumnIndex": 0,
                "endColumnIndex": 12,
            }
            requests.extend(
                [
                    {
                        "copyPaste": {
                            "source": source,
                            "destination": destination,
                            "pasteType": "PASTE_FORMAT",
                            "pasteOrientation": "NORMAL",
                        }
                    },
                    {
                        "copyPaste": {
                            "source": source,
                            "destination": destination,
                            "pasteType": "PASTE_DATA_VALIDATION",
                            "pasteOrientation": "NORMAL",
                        }
                    },
                ]
            )

        requests.append(
            {
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": target_row - 1,
                        "endRowIndex": target_row,
                        "startColumnIndex": 0,
                        "endColumnIndex": 12,
                    },
                    "rows": [{"values": cells}],
                    "fields": "userEnteredValue,textFormatRuns",
                }
            }
        )

        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": requests},
        ).execute()

    def export(self, payload):
        required = ("property_url", "phone_number", "phone_found_at")
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise GoogleSheetsStructureError(
                "Lead cannot be exported; missing required fields: "
                + ", ".join(missing)
            )

        phone_found_at = payload["phone_found_at"]
        if phone_found_at.tzinfo is None:
            phone_found_at = phone_found_at.replace(tzinfo=timezone.utc)
        event_date = phone_found_at.astimezone(UK_TZ)
        target_month = event_date.strftime("%B")

        sheet, values, first_data_row, cadence, created = self._ensure_month_tab(
            target_month
        )
        listing_id = str(payload.get("listing_id") or "")
        existing_row = self._find_existing_row(
            values,
            payload["property_url"],
            listing_id,
        )
        lead_rows = self._lead_rows(values)
        occupied_rows = set(self._occupied_rows(values))

        if existing_row:
            target_row = existing_row
            source_format_row = existing_row
            action = "update"
        else:
            target_row = first_data_row
            last_occupied = max(occupied_rows) if occupied_rows else 0
            while target_row <= last_occupied or target_row in occupied_rows:
                target_row += cadence
            format_rows = [
                row
                for row in lead_rows
                if row < target_row
                and (row - first_data_row) % cadence == 0
            ]
            source_format_row = max(format_rows) if format_rows else first_data_row
            action = "insert"

        row_values, cells = self._build_row(payload, event_date)
        digest = payload_hash(
            {
                "tab": target_month,
                "row": target_row,
                "values": row_values,
                "listing_id": listing_id,
            }
        )

        logger.info(
            "GOOGLE_SHEETS_EXPORT_START "
            f"export_id={payload.get('export_id')} conversation_id={payload.get('conversation_id')} "
            f"thread_id={payload.get('thread_id')} listing_id={listing_id} "
            f"tab={target_month} row={target_row} action={action} "
            f"tab_created={created} cadence={cadence}"
        )

        self._write_row(
            sheet=sheet,
            values=values,
            target_row=target_row,
            source_format_row=source_format_row,
            cells=cells,
        )

        logger.info(
            "GOOGLE_SHEETS_EXPORT_SUCCESS "
            f"export_id={payload.get('export_id')} listing_id={listing_id} "
            f"tab={target_month} row={target_row} action={action} payload_hash={digest}"
        )
        return {
            "tab": target_month,
            "row": target_row,
            "action": action,
            "payload_hash": digest,
            "tab_created": created,
        }

    def audit(self):
        metadata = self._spreadsheet_metadata()
        sheets = self._sheet_properties(metadata)
        results = []
        for sheet in sheets:
            title = sheet["title"]
            values = self._get_values(title)
            header_ok = True
            header_error = None
            try:
                self._validate_headers(title, values)
            except GoogleSheetsStructureError as exc:
                header_ok = False
                header_error = str(exc)
            lead_rows = self._lead_rows(values)
            validation = self._inspect_person_validation(
                title,
                lead_rows[0] if lead_rows else 3,
            )
            results.append(
                {
                    "title": title,
                    "sheet_id": sheet["sheetId"],
                    "row_count": sheet.get("gridProperties", {}).get("rowCount"),
                    "header_ok": header_ok,
                    "header_error": header_error,
                    "lead_rows": lead_rows,
                    "first_data_row": lead_rows[0] if lead_rows else None,
                    "cadence": self._infer_cadence(lead_rows),
                    "last_lead_row": lead_rows[-1] if lead_rows else None,
                    "person_validation": validation,
                }
            )

        logger.info(
            "GOOGLE_SHEETS_AUDIT_SUCCESS "
            f"spreadsheet_id={self.spreadsheet_id} tabs={len(results)} "
            f"valid_tabs={sum(1 for result in results if result['header_ok'])}"
        )
        return {
            "spreadsheet_id": metadata.get("spreadsheetId"),
            "title": metadata.get("properties", {}).get("title"),
            "timezone": metadata.get("properties", {}).get("timeZone"),
            "tabs": results,
        }

    def _inspect_person_validation(self, tab_name, row_number):
        try:
            response = (
                self.service.spreadsheets()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    ranges=[f"{quote_sheet_name(tab_name)}!A{row_number}"],
                    includeGridData=True,
                    fields="sheets(data(rowData(values(dataValidation))))",
                )
                .execute()
            )
            values = (
                response.get("sheets", [{}])[0]
                .get("data", [{}])[0]
                .get("rowData", [{}])[0]
                .get("values", [{}])
            )
            rule = values[0].get("dataValidation") if values else None
            if not rule:
                return {
                    "present": False,
                    "accepts_person": None,
                    "person": self.person,
                }

            condition = rule.get("condition", {})
            condition_type = condition.get("type")
            allowed = [
                value.get("userEnteredValue", "")
                for value in condition.get("values", [])
            ]
            accepts = None
            if condition_type == "ONE_OF_LIST":
                accepts = self.person in allowed
            return {
                "present": True,
                "strict": bool(rule.get("strict")),
                "condition_type": condition_type,
                "allowed_values": allowed if condition_type == "ONE_OF_LIST" else None,
                "accepts_person": accepts,
                "person": self.person,
            }
        except Exception as exc:
            logger.warning(
                "GOOGLE_SHEETS_VALIDATION_AUDIT_FAILED "
                f"tab={tab_name} row={row_number} error={exc}"
            )
            return {
                "present": None,
                "accepts_person": None,
                "person": self.person,
                "error": str(exc),
            }


def configured_exporter(service=None):
    validate_enabled_config()
    return GoogleSheetsLeadExporter(
        service or build_sheets_service(),
        settings.GOOGLE_SHEET_ID,
        person=settings.GOOGLE_SHEET_PERSON or "Becky",
        template_tab=settings.GOOGLE_SHEET_TEMPLATE_TAB,
    )
