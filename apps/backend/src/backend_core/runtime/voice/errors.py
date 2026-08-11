class VoiceRuntimeError(Exception):
    pass


class RuntimeNotFoundError(VoiceRuntimeError):
    pass


class RuntimeDraftExistsError(VoiceRuntimeError):
    pass


class RuntimeRevisionImmutableError(VoiceRuntimeError):
    pass


class RuntimeRevisionVersionConflictError(VoiceRuntimeError):
    pass


class VoiceRuntimeResolutionError(VoiceRuntimeError):
    def __init__(self, path: str, code: str, message: str) -> None:
        super().__init__(message)
        self.path = path
        self.code = code
        self.message = message
