from typing import Any

from pydantic import BaseModel


class GoogleSheetsAppendRowRequest(BaseModel):
    spreadsheet_id: str
    sheet_name: str
    values: list[Any]


class GoogleSheetsAppendRowResult(BaseModel):
    spreadsheet_id: str
    sheet_name: str
    updated_range: str | None = None
    updated_rows: int | None = None


class GoogleSheetsReadRequest(BaseModel):
    spreadsheet_id: str
    sheet_name: str
    table_range: str


class GoogleSheetsReadResult(BaseModel):
    values: list[list[Any]]
