from enum import Enum


class PostCallActionInputRepresentation(str, Enum):
    BASE64_TEXT = "base64_text"
    ORIGINAL = "original"
    PLAIN_TEXT = "plain_text"
    RAW_JSON = "raw_json"

    def __str__(self) -> str:
        return str(self.value)
