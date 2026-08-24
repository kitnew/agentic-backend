from enum import Enum


class AuthoringStateSource(str, Enum):
    DRAFT = "draft"
    EMPTY = "empty"
    PUBLISHED = "published"

    def __str__(self) -> str:
        return str(self.value)
