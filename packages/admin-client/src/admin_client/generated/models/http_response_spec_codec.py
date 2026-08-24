from enum import Enum


class HttpResponseSpecCodec(str, Enum):
    JSON = "json"
    NONE = "none"
    TEXT = "text"

    def __str__(self) -> str:
        return str(self.value)
