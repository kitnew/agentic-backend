class VoiceServiceError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.public_message = message


class VoiceDisabledError(VoiceServiceError):
    status_code = 403


class VoiceValidationError(VoiceServiceError):
    status_code = 400


class VoiceProviderConfigurationError(VoiceServiceError):
    status_code = 500


class VoiceProviderNotFoundError(VoiceServiceError):
    status_code = 400


class VoiceSTTProviderError(VoiceServiceError):
    status_code = 502


class EmptyTranscriptError(VoiceServiceError):
    status_code = 422


class VoiceAgentProcessingError(VoiceServiceError):
    status_code = 502


class VoiceTTSProviderError(VoiceServiceError):
    status_code = 502
