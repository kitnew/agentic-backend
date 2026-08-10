from enum import Enum


class PromptSetPlanResponseStatus(str, Enum):
    MISSING_ACTIVE = "missing-active"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"

    def __str__(self) -> str:
        return str(self.value)
