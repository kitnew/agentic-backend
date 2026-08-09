from enum import Enum


class CallLifecycleStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CREATED = "created"
    FAILED = "failed"

    def __str__(self) -> str:
        return str(self.value)
