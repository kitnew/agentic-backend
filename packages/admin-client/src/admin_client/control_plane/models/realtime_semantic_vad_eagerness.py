from enum import Enum


class RealtimeSemanticVADEagerness(str, Enum):
    AUTO = "auto"
    HIGH = "high"
    LOW = "low"
    MEDIUM = "medium"

    def __str__(self) -> str:
        return str(self.value)
