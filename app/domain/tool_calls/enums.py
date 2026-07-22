from enum import Enum


class ToolCallStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    DISABLED = "disabled"
    SKIPPED = "skipped"
