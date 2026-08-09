from enum import Enum


class ConversationPersistenceStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    OPEN = "open"

    def __str__(self) -> str:
        return str(self.value)
