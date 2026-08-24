from enum import Enum


class HttpOperationMethod(str, Enum):
    DELETE = "DELETE"
    GET = "GET"
    PATCH = "PATCH"
    POST = "POST"
    PUT = "PUT"

    def __str__(self) -> str:
        return str(self.value)
