from enum import Enum


class TranscriptArtifactInputRepresentation(str, Enum):
    PLAIN_TEXT = "plain_text"
    RAW_JSON = "raw_json"

    def __str__(self) -> str:
        return str(self.value)
