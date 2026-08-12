from enum import Enum


class CallDirection(str, Enum):
    INBOUND = "inbound"

    def __str__(self) -> str:
        return str(self.value)
