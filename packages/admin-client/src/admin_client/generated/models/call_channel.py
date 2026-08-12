from enum import Enum


class CallChannel(str, Enum):
    SIP = "sip"
    WEB = "web"

    def __str__(self) -> str:
        return str(self.value)
