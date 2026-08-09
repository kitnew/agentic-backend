from enum import Enum


class IntegrationConnectionStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    INVALID = "invalid"

    def __str__(self) -> str:
        return str(self.value)
