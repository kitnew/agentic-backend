from enum import Enum


class CredentialResponseStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"

    def __str__(self) -> str:
        return str(self.value)
