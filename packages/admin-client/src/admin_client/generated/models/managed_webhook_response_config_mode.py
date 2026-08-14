from enum import Enum


class ManagedWebhookResponseConfigMode(str, Enum):
    JSON = "json"
    STATUS_ONLY = "status_only"
    TEXT = "text"

    def __str__(self) -> str:
        return str(self.value)
