from enum import Enum


class ConversationScope(str, Enum):
    PROPERTY_ONLY = "property_only"

    def __str__(self) -> str:
        return str(self.value)
