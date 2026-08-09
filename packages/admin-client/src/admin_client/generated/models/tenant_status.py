from enum import Enum


class TenantStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    SUSPENDED = "suspended"

    def __str__(self) -> str:
        return str(self.value)
