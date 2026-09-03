from __future__ import annotations

import nats
from nats.aio.client import Client as NatsClient
from nats.js.api import StorageType, StreamConfig
from nats.js.client import JetStreamContext
from nats.js.errors import NotFoundError

from control_plane.application.ports.messaging import OutboundMessage


class NatsMessagePublisher:
    STREAM_NAME = "CONTROL_PLANE_EVENTS"
    STREAM_SUBJECTS = ("evt.configuration.>", "evt.control_plane.>")

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: NatsClient | None = None
        self._jetstream: JetStreamContext | None = None

    async def connect(self) -> None:
        self._client = await nats.connect(self._url)
        self._jetstream = self._client.jetstream()
        config = StreamConfig(
            name=self.STREAM_NAME,
            subjects=list(self.STREAM_SUBJECTS),
            storage=StorageType.FILE,
        )
        try:
            info = await self._jetstream.stream_info(self.STREAM_NAME)
        except NotFoundError:
            await self._jetstream.add_stream(config=config)
        else:
            if (
                info.config.subjects != config.subjects
                or info.config.storage != config.storage
            ):
                info.config.subjects = config.subjects
                info.config.storage = config.storage
                await self._jetstream.update_stream(config=info.config)

    @property
    def ready(self) -> bool:
        return (
            self._client is not None
            and self._client.is_connected
            and self._jetstream is not None
        )

    async def ping(self) -> None:
        if not self.ready:
            raise RuntimeError("NATS is not connected")
        assert self._jetstream is not None
        await self._jetstream.stream_info(self.STREAM_NAME)

    async def publish(self, message: OutboundMessage) -> None:
        if self._jetstream is None:
            raise RuntimeError("JetStream is not connected")
        headers = {"Nats-Msg-Id": message.message_id} if message.message_id else None
        await self._jetstream.publish(
            message.subject,
            message.payload,
            headers=headers,
            stream=self.STREAM_NAME,
            timeout=5,
        )

    async def drain(self) -> None:
        if self._client is not None and self._client.is_connected:
            await self._client.drain()

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.close()
        self._client = None
        self._jetstream = None
