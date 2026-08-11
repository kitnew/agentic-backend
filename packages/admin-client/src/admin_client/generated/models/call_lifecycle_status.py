from enum import Enum


class CallLifecycleStatus(str, Enum):
    CONNECTED = "connected"
    CREATED = "created"
    ENDED = "ended"
    FAILED = "failed"
    STARTED = "started"

    def __str__(self) -> str:
        return str(self.value)
