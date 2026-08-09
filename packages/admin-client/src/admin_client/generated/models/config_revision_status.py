from enum import Enum


class ConfigRevisionStatus(str, Enum):
    ARCHIVED = "archived"
    DRAFT = "draft"
    PUBLISHED = "published"

    def __str__(self) -> str:
        return str(self.value)
