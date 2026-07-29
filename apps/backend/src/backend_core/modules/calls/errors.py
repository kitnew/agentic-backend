class CallSessionError(Exception):
    pass


class CallSessionNotFoundError(CallSessionError):
    pass


class CallSessionConflictError(CallSessionError):
    pass


class CallSessionConfigUnavailableError(CallSessionError):
    pass


class CallSessionRouteUnavailableError(CallSessionError):
    pass
