from typing import Protocol

from contracts import MessageEnvelope


class EventBus(Protocol):
    async def publish(self, event: MessageEnvelope) -> None: ...


class CommandBus(Protocol):
    async def send(self, command: MessageEnvelope) -> None: ...
