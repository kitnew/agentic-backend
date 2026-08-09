from enum import Enum


class GoogleSheetsAppendExecutionValueInputOption(str, Enum):
    RAW = "RAW"
    USER_ENTERED = "USER_ENTERED"

    def __str__(self) -> str:
        return str(self.value)
