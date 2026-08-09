from enum import Enum


class IntegrationProvider(str, Enum):
    GOOGLE_SHEETS = "google_sheets"
    MANAGED_WEBHOOK = "managed_webhook"

    def __str__(self) -> str:
        return str(self.value)
