from enum import Enum


class IntegrationValidateResponseCredentials(str, Enum):
    CONFIGURED = "configured"
    MISSING = "missing"
    NOT_REQUIRED = "not_required"
    REVOKED = "revoked"

    def __str__(self) -> str:
        return str(self.value)
