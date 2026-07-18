from enum import Enum


class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    DISABLED = "disabled"
    SKIPPED = "skipped"
