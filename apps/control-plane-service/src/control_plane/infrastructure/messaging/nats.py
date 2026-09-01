from __future__ import annotations

import nats
from nats.aio.client import Client as NatsClient

from control_plane.application.ports.messaging import OutboundMessage


class NatsMessagePublisher:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client: NatsClient | None = None

    async def connect(self) -> None:
        self._client = await nats.connect(self._url)

    @property
    def ready(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def ping(self) -> None:
        if not self.ready:
            raise RuntimeError("NATS is not connected")

    async def publish(self, message: OutboundMessage) -> None:
        if self._client is None:
            raise RuntimeError("NATS is not connected")
        await self._client.publish(message.subject, message.payload)

    async def drain(self) -> None:
        if self._client is not None and self._client.is_connected:
            await self._client.drain()

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.close()
        self._client = None
