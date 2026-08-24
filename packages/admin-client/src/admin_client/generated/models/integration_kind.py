from enum import Enum


class IntegrationKind(str, Enum):
    GOOGLE_SHEETS = "google_sheets"
    HTTP = "http"

    def __str__(self) -> str:
        return str(self.value)
