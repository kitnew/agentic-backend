from app.integrations.google_sheets.client import GoogleSheetsClient
from app.integrations.google_sheets.schemas import GoogleSheetsAppendRowRequest


class Request:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result() if callable(self.result) else self.result


class Values:
    def __init__(self, sheets):
        self.sheets = sheets

    def get(self, **_kwargs):
        return Request({"values": [["Prepis hovoru"]] + self.sheets.rows})


class Metadata:
    def __init__(self, sheets):
        self.sheets = sheets

    def search(self, *, body, **_kwargs):
        key = body["dataFilters"][0]["developerMetadataLookup"]["metadataValue"]
        return Request(
            lambda: {
                "matchedDeveloperMetadata": [{}] if key in self.sheets.keys else []
            }
        )


class Spreadsheets:
    def __init__(self):
        self.keys = set()
        self.rows = []
        self.batch_calls = 0

    def developerMetadata(self):
        return Metadata(self)

    def values(self):
        return Values(self)

    def get(self, **_kwargs):
        return Request({"sheets": [{"properties": {"sheetId": 7, "title": "Transkripty"}}]})

    def batchUpdate(self, *, body, **_kwargs):
        def execute():
            self.batch_calls += 1
            requests = body["requests"]
            values = requests[0]["updateCells"]["rows"][0]["values"]
            self.rows.append([cell["userEnteredValue"]["stringValue"] for cell in values])
            self.keys.add(
                requests[1]["createDeveloperMetadata"]["developerMetadata"]["metadataValue"]
            )
            return {}

        return Request(execute)


class Service:
    def __init__(self):
        self.resource = Spreadsheets()

    def spreadsheets(self):
        return self.resource


def test_google_sheets_append_once_uses_external_call_session_key(monkeypatch):
    service = Service()
    client = GoogleSheetsClient("/tmp/not-read.json")
    monkeypatch.setattr(client, "_build_service", lambda _scopes: service)
    request = GoogleSheetsAppendRowRequest(
        spreadsheet_id="sheet-id",
        sheet_name="Transkripty",
        values=["transcript", "summary", "time", "+421900111222"],
    )
    first = client.append_row_once(request, idempotency_key="call-1")
    second = client.append_row_once(request, idempotency_key="call-1")
    assert first.updated_rows == 1 and second.updated_rows == 0
    assert service.resource.batch_calls == 1
    assert service.resource.rows == [request.values]
