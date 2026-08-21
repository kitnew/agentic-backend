from enum import Enum


class LLMRuntimeSettingsReasoningEffortType0(str, Enum):
    HIGH = "high"
    LOW = "low"
    MAX = "max"
    MEDIUM = "medium"
    NONE = "none"
    XHIGH = "xhigh"

    def __str__(self) -> str:
        return str(self.value)
