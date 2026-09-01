import pytest
from control_plane.application.ports import OutboundMessage
from control_plane.infrastructure.messaging.nats import NatsMessagePublisher
from nats.js.errors import NotFoundError


class FakeJetStream:
    def __init__(self) -> None:
        self.config = None
        self.published: list[tuple[str, bytes, dict | None, str | None]] = []

    async def stream_info(self, _name: str):
        if self.config is None:
            raise NotFoundError
        return type("Info", (), {"config": self.config})()

    async def add_stream(self, config):
        self.config = config

    async def update_stream(self, config):
        self.config = config

    async def publish(
        self, subject, payload, *, headers=None, stream=None, timeout=None
    ):
        assert timeout == 5
        self.published.append((subject, payload, headers, stream))


class FakeNatsClient:
    def __init__(self) -> None:
        self.is_connected = True
        self.is_closed = False
        self.js = FakeJetStream()
        self.drained = False

    def jetstream(self) -> FakeJetStream:
        return self.js

    async def drain(self) -> None:
        self.drained = True

    async def close(self) -> None:
        self.is_closed = True
        self.is_connected = False


@pytest.mark.asyncio
async def test_nats_adapter_connects_publishes_drains_and_closes(monkeypatch) -> None:
    client = FakeNatsClient()

    async def connect(url: str) -> FakeNatsClient:
        assert url == "nats://example:4222"
        return client

    monkeypatch.setattr(
        "control_plane.infrastructure.messaging.nats.nats.connect", connect
    )

    publisher = NatsMessagePublisher("nats://example:4222")
    await publisher.connect()
    await publisher.publish(
        OutboundMessage("events", b"serialized-message", "event-id")
    )
    await publisher.drain()
    await publisher.close()

    assert client.js.published == [
        (
            "events",
            b"serialized-message",
            {"Nats-Msg-Id": "event-id"},
            "CONTROL_PLANE_EVENTS",
        )
    ]
    assert client.js.config.subjects == ["evt.configuration.>", "evt.control_plane.>"]
    assert client.drained
    assert client.is_closed


@pytest.mark.asyncio
async def test_nats_failed_connect_leaves_safe_shutdown_state(monkeypatch) -> None:
    async def connect(_url: str) -> FakeNatsClient:
        raise RuntimeError("connect failed")

    monkeypatch.setattr(
        "control_plane.infrastructure.messaging.nats.nats.connect", connect
    )

    publisher = NatsMessagePublisher("nats://example:4222")
    with pytest.raises(RuntimeError, match="connect failed"):
        await publisher.connect()

    await publisher.drain()
    await publisher.close()
    assert not publisher.ready


@pytest.mark.asyncio
async def test_nats_adapter_reports_not_ready_before_connect() -> None:
    publisher = NatsMessagePublisher("nats://example:4222")

    assert not publisher.ready
    with pytest.raises(RuntimeError, match="NATS is not connected"):
        await publisher.ping()


@pytest.mark.asyncio
async def test_nats_close_is_safe_after_drain_and_on_repeated_close(
    monkeypatch,
) -> None:
    client = FakeNatsClient()

    async def connect(_url: str) -> FakeNatsClient:
        return client

    monkeypatch.setattr(
        "control_plane.infrastructure.messaging.nats.nats.connect", connect
    )

    publisher = NatsMessagePublisher("nats://example:4222")
    await publisher.connect()
    await publisher.drain()
    await publisher.close()
    await publisher.close()

    assert client.drained
    assert client.is_closed
