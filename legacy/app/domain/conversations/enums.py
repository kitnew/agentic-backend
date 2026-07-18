from enum import Enum


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    FAILED = "failed"
