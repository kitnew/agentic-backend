import os
from pathlib import Path

from dotenv import load_dotenv

from app.integrations.google_sheets.schemas import (
    GoogleSheetsAppendRowRequest,
    GoogleSheetsAppendRowResult,
)


APP_DIR = Path(__file__).resolve().parents[2]
load_dotenv(APP_DIR / ".env")


class GoogleSheetsClient:
    scopes = ("https://www.googleapis.com/auth/spreadsheets",)

    def __init__(self, service_account_file: str | None = None):
        configured_file = (
            service_account_file
            or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        )
        self.service_account_file = self._resolve_service_account_file(configured_file)

    def append_row(self, request: GoogleSheetsAppendRowRequest) -> GoogleSheetsAppendRowResult:
        service = self._build_service()
        response = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=request.spreadsheet_id,
                range=f"{request.sheet_name}!A:G",
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

    def _build_service(self):
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
            scopes=self.scopes,
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
