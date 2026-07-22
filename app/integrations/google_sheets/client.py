import os
from pathlib import Path

from dotenv import load_dotenv

from app.integrations.google_sheets.schemas import (
    GoogleSheetsAppendRowRequest,
    GoogleSheetsAppendRowResult,
    GoogleSheetsReadRequest,
    GoogleSheetsReadResult,
)


APP_DIR = Path(__file__).resolve().parents[2]
load_dotenv(APP_DIR / ".env")


class GoogleSheetsClient:
    read_scopes = ("https://www.googleapis.com/auth/spreadsheets.readonly",)
    write_scopes = ("https://www.googleapis.com/auth/spreadsheets",)

    def __init__(self, service_account_file: str | None = None):
        configured_file = (
            service_account_file
            or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        )
        self.service_account_file = self._resolve_service_account_file(configured_file)

    def append_row(self, request: GoogleSheetsAppendRowRequest) -> GoogleSheetsAppendRowResult:
        service = self._build_service(self.write_scopes)
        response = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=request.spreadsheet_id,
                range=f"{request.sheet_name}!A:L",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [request.values]},
            )
            .execute()
        )

        updates = response.get("updates", {})
        return GoogleSheetsAppendRowResult(
            spreadsheet_id=request.spreadsheet_id,
            sheet_name=request.sheet_name,
            updated_range=updates.get("updatedRange"),
            updated_rows=updates.get("updatedRows"),
        )

    def append_row_once(
        self, request: GoogleSheetsAppendRowRequest, *, idempotency_key: str
    ) -> GoogleSheetsAppendRowResult:
        service = self._build_service(self.write_scopes)
        search = (
            service.spreadsheets()
            .developerMetadata()
            .search(
                spreadsheetId=request.spreadsheet_id,
                body={
                    "dataFilters": [
                        {
                            "developerMetadataLookup": {
                                "metadataKey": "call_session_id",
                                "metadataValue": idempotency_key,
                                "visibility": "DOCUMENT",
                            }
                        }
                    ]
                },
            )
            .execute()
        )
        if search.get("matchedDeveloperMetadata"):
            return GoogleSheetsAppendRowResult(
                spreadsheet_id=request.spreadsheet_id,
                sheet_name=request.sheet_name,
                updated_rows=0,
            )

        spreadsheet = (
            service.spreadsheets()
            .get(
                spreadsheetId=request.spreadsheet_id,
                fields="sheets(properties(sheetId,title))",
            )
            .execute()
        )
        sheet = next(
            (
                item["properties"]
                for item in spreadsheet.get("sheets", [])
                if item.get("properties", {}).get("title") == request.sheet_name
            ),
            None,
        )
        if sheet is None:
            raise RuntimeError(f"Google Sheets tab not found: {request.sheet_name}")
        escaped_name = request.sheet_name.replace("'", "''")
        existing = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=request.spreadsheet_id,
                range=f"'{escaped_name}'!A:A",
                majorDimension="COLUMNS",
            )
            .execute()
        )
        columns = existing.get("values", [])
        row_index = len(columns[0]) if columns else 0
        cells = [
            {"userEnteredValue": {"stringValue": "" if value is None else str(value)}}
            for value in request.values
        ]
        (
            service.spreadsheets()
            .batchUpdate(
                spreadsheetId=request.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateCells": {
                                "start": {
                                    "sheetId": sheet["sheetId"],
                                    "rowIndex": row_index,
                                    "columnIndex": 0,
                                },
                                "rows": [{"values": cells}],
                                "fields": "userEnteredValue",
                            }
                        },
                        {
                            "createDeveloperMetadata": {
                                "developerMetadata": {
                                    "metadataKey": "call_session_id",
                                    "metadataValue": idempotency_key,
                                    "visibility": "DOCUMENT",
                                    "location": {
                                        "dimensionRange": {
                                            "sheetId": sheet["sheetId"],
                                            "dimension": "ROWS",
                                            "startIndex": row_index,
                                            "endIndex": row_index + 1,
                                        }
                                    },
                                }
                            }
                        },
                    ]
                },
            )
            .execute()
        )
        return GoogleSheetsAppendRowResult(
            spreadsheet_id=request.spreadsheet_id,
            sheet_name=request.sheet_name,
            updated_range=(
                f"{request.sheet_name}!A{row_index + 1}:"
                f"{_column_name(len(request.values))}{row_index + 1}"
            ),
            updated_rows=1,
        )

    def read_values(self, request: GoogleSheetsReadRequest) -> GoogleSheetsReadResult:
        service = self._build_service(self.read_scopes)
        response = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=request.spreadsheet_id,
                range=f"{request.sheet_name}!{request.table_range}",
                majorDimension="ROWS",
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER",
            )
            .execute()
        )
        return GoogleSheetsReadResult(values=response.get("values", []))

    def _build_service(self, scopes):
        if not self.service_account_file:
            raise RuntimeError(
                "Google Sheets credentials are not configured. Set GOOGLE_SERVICE_ACCOUNT_FILE "
                "or GOOGLE_APPLICATION_CREDENTIALS."
            )

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google Sheets dependencies are not installed. Install google-api-python-client "
                "and google-auth."
            ) from exc

        credentials = service_account.Credentials.from_service_account_file(
            self.service_account_file,
            scopes=scopes,
        )
        return build("sheets", "v4", credentials=credentials)

    def _resolve_service_account_file(self, service_account_file: str | None) -> str | None:
        if not service_account_file:
            return None

        path = Path(service_account_file)
        if path.is_absolute():
            return str(path)

        app_relative_path = APP_DIR / path
        if app_relative_path.exists():
            return str(app_relative_path)

        return str(path)


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name
