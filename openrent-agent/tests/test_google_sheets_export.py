from datetime import datetime

from app.integrations.google_sheets import GoogleSheetsLeadExporter


HEADERS = [
    "Person",
    "Date",
    "Direction",
    "Name of Landlord",
    "Phone Number",
    "Address",
    "Specifics",
    "Rent amount",
    "",
    "",
    "",
    "OpenRent Links",
]


class FakeRequest:
    def __init__(self, callback):
        self.callback = callback

    def execute(self):
        return self.callback()


class FakeValuesResource:
    def __init__(self, state):
        self.state = state

    def get(self, *, spreadsheetId, range, valueRenderOption=None):
        del spreadsheetId, valueRenderOption
        tab = range.split("!", 1)[0].strip("'").replace("''", "'")
        return FakeRequest(lambda: {"values": self.state["values"].get(tab, [])})


class FakeSpreadsheetsResource:
    def __init__(self, state):
        self.state = state

    def get(self, **kwargs):
        del kwargs
        return FakeRequest(
            lambda: {
                "spreadsheetId": "sheet-1",
                "properties": {"title": "Daily Report Sheet", "timeZone": "Europe/London"},
                "sheets": [{"properties": sheet} for sheet in self.state["sheets"]],
            }
        )

    def values(self):
        return FakeValuesResource(self.state)

    def batchUpdate(self, *, spreadsheetId, body):
        del spreadsheetId

        def apply():
            self.state["requests"].append(body)
            for request in body.get("requests", []):
                duplicate = request.get("duplicateSheet")
                if duplicate:
                    source = next(
                        sheet
                        for sheet in self.state["sheets"]
                        if sheet["sheetId"] == duplicate["sourceSheetId"]
                    )
                    new_sheet = {
                        **source,
                        "sheetId": duplicate["newSheetId"],
                        "title": duplicate["newSheetName"],
                        "index": duplicate["insertSheetIndex"],
                        "gridProperties": dict(source["gridProperties"]),
                    }
                    self.state["sheets"].append(new_sheet)
                    source_values = self.state["values"][source["title"]]
                    self.state["values"][new_sheet["title"]] = [list(source_values[0])]
            return {"replies": []}

        return FakeRequest(apply)


class FakeService:
    def __init__(self, state):
        self.resource = FakeSpreadsheetsResource(state)

    def spreadsheets(self):
        return self.resource


def make_payload(month=6):
    return {
        "export_id": 1,
        "conversation_id": 2,
        "thread_id": "T1",
        "listing_id": "2884260",
        "property_url": "https://www.openrent.co.uk/2884260",
        "phone_number": "07123456789",
        "phone_found_at": datetime(2026, month, 19, 12, 0, 0),
        "landlord_name": "Catherine S",
        "address": "10 High Road, RM6",
        "bedrooms": 2,
        "bathrooms": 1,
        "rent_pcm": 1599,
    }


def test_export_uses_next_formatted_lead_row():
    state = {
        "sheets": [
            {
                "sheetId": 10,
                "title": "June",
                "index": 0,
                "gridProperties": {"rowCount": 1000, "columnCount": 12},
            }
        ],
        "values": {
            "June": [
                HEADERS,
                [],
                ["Pooja", "01/06/2026", "", "A", "07111", "Addr", "2 bed 1 bath", 1000, "", "", "", "https://www.openrent.co.uk/11111"],
                [],
                ["Pooja", "02/06/2026", "", "B", "07222", "Addr", "2 bed 1 bath", 1200, "", "", "", "https://www.openrent.co.uk/22222"],
            ]
        },
        "requests": [],
    }
    exporter = GoogleSheetsLeadExporter(FakeService(state), "sheet-1", person="Becky")

    result = exporter.export(make_payload())

    assert result["tab"] == "June"
    assert result["row"] == 7
    assert result["action"] == "insert"
    requests = state["requests"][-1]["requests"]
    copy_format = requests[0]["copyPaste"]
    assert copy_format["destination"]["startRowIndex"] == 6
    assert copy_format["destination"]["endRowIndex"] == 7
    update = requests[-1]["updateCells"]
    assert update["range"]["startRowIndex"] == 6
    cells = update["rows"][0]["values"]
    assert cells[0]["userEnteredValue"]["stringValue"] == "Becky"
    assert cells[2]["userEnteredValue"]["stringValue"] == ""
    assert cells[4]["userEnteredValue"]["stringValue"] == "07123456789"


def test_export_updates_existing_listing_row():
    payload = make_payload()
    state = {
        "sheets": [
            {
                "sheetId": 10,
                "title": "June",
                "index": 0,
                "gridProperties": {"rowCount": 1000, "columnCount": 12},
            }
        ],
        "values": {
            "June": [
                HEADERS,
                [],
                ["Old", "01/06/2026", "", "", "", "", "", "", "", "", "", payload["property_url"]],
            ]
        },
        "requests": [],
    }
    exporter = GoogleSheetsLeadExporter(FakeService(state), "sheet-1", person="Becky")

    result = exporter.export(payload)

    assert result["row"] == 3
    assert result["action"] == "update"


def test_export_creates_missing_month_from_previous_month():
    state = {
        "sheets": [
            {
                "sheetId": 10,
                "title": "June",
                "index": 0,
                "gridProperties": {"rowCount": 1000, "columnCount": 12},
            }
        ],
        "values": {
            "June": [
                HEADERS,
                [],
                ["Pooja", "01/06/2026", "", "A", "07111", "Addr", "2 bed 1 bath", 1000, "", "", "", "https://www.openrent.co.uk/11111"],
            ]
        },
        "requests": [],
    }
    exporter = GoogleSheetsLeadExporter(FakeService(state), "sheet-1", person="Becky")

    result = exporter.export(make_payload(month=7))

    assert result["tab"] == "July"
    assert result["tab_created"] is True
    assert result["row"] == 3
    create_requests = state["requests"][0]["requests"]
    assert create_requests[0]["duplicateSheet"]["newSheetName"] == "July"
    assert create_requests[1]["updateCells"]["range"]["startRowIndex"] == 1
