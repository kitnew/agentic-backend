import pytest
from control_plane.application.ports import OutboundMessage
from control_plane.infrastructure.messaging.nats import NatsMessagePublisher


class FakeNatsClient:
    def __init__(self) -> None:
        self.is_connected = True
        self.is_closed = False
        self.published: list[tuple[str, bytes]] = []
        self.drained = False

    async def publish(self, subject: str, payload: bytes) -> None:
        self.published.append((subject, payload))

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
    await publisher.publish(OutboundMessage("events", b"serialized-message"))
    await publisher.drain()
    await publisher.close()

    assert client.published[0][0] == "events"
    assert client.published[0][1] == b"serialized-message"
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
