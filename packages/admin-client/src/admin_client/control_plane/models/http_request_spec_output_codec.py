from enum import Enum


class HttpRequestSpecOutputCodec(str, Enum):
    JSON = "json"
    NONE = "none"
    TEXT = "text"

    def __str__(self) -> str:
        return str(self.value)
