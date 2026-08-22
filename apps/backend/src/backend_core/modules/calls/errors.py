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


class CallSessionTelephonyNotReadyError(CallSessionError):
    pass


class HumanHandoffError(CallSessionError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
