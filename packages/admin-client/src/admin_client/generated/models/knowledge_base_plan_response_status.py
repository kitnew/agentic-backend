from enum import Enum


class KnowledgeBasePlanResponseStatus(str, Enum):
    MODIFIED = "modified"
    UNCHANGED = "unchanged"

    def __str__(self) -> str:
        return str(self.value)
