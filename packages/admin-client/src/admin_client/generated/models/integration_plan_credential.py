from enum import Enum


class IntegrationPlanCredential(str, Enum):
    ROTATE = "rotate"
    UNCHANGED = "unchanged"

    def __str__(self) -> str:
        return str(self.value)
