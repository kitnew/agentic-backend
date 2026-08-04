class ConversationError(Exception):
    pass


class ConversationNotFoundError(ConversationError):
    pass


class ConversationConflictError(ConversationError):
    pass


class ConversationMessageConflictError(ConversationError):
    pass

