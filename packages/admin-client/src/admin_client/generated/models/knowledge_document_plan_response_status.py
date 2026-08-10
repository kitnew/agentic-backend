from enum import Enum


class KnowledgeDocumentPlanResponseStatus(str, Enum):
    LOCAL_ONLY = "local-only"
    MISSING_LOCAL = "missing-local"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"

    def __str__(self) -> str:
        return str(self.value)
