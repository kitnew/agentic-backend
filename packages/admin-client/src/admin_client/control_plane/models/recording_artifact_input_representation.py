from enum import Enum


class RecordingArtifactInputRepresentation(str, Enum):
    BASE64_TEXT = "base64_text"
    ORIGINAL = "original"

    def __str__(self) -> str:
        return str(self.value)
