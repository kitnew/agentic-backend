from enum import Enum


class KnowledgeDocumentPlanResponseAction(str, Enum):
    CREATE = "create"
    REMOVE = "remove"
    REUSE = "reuse"

    def __str__(self) -> str:
        return str(self.value)
