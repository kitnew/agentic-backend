from enum import Enum


class CreateIntegrationConnectionRequestKind(str, Enum):
    GOOGLE_SHEETS = "google_sheets"
    HTTP = "http"

    def __str__(self) -> str:
        return str(self.value)
