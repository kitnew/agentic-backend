from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    subject: str
    payload: bytes
    message_id: str | None = None


class MessagePublisher(Protocol):
    async def publish(self, message: OutboundMessage) -> None: ...
