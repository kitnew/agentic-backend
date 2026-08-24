from enum import Enum


class AuthoringChangeOperation(str, Enum):
    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"

    def __str__(self) -> str:
        return str(self.value)
