from enum import Enum


class IntegrationReadinessConfiguration(str, Enum):
    INCOMPLETE = "incomplete"
    INVALID = "invalid"
    VALID = "valid"

    def __str__(self) -> str:
        return str(self.value)
