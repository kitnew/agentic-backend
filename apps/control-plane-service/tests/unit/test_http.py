import asyncio
from contextlib import asynccontextmanager

import pytest
from control_plane.interfaces.http import create_http_app
from control_plane.runtime import LifecycleState, Readiness, ServiceLifecycle
from control_plane.runtime import lifecycle as lifecycle_module
from httpx import ASGITransport, AsyncClient


class FakeLifecycle:
    state = LifecycleState.CREATED

    def __init__(self, readiness: Readiness) -> None:
        self.readiness_value = readiness

    @asynccontextmanager
    async def lifespan(self, _app):
        yield

    async def readiness(self) -> Readiness:
        return self.readiness_value


@pytest.mark.asyncio
async def test_health_does_not_require_dependencies() -> None:
    lifecycle = FakeLifecycle(
        Readiness(
            postgres=False,
            control_plane_schema=False,
            nats=False,
            outbox_relay=False,
        )
    )
    app = create_http_app(lifecycle)  # type: ignore[arg-type]

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "control-plane-service",
    }


@pytest.mark.asyncio
async def test_ready_reports_unavailable_dependencies() -> None:
    lifecycle = FakeLifecycle(
        Readiness(
            postgres=False,
            control_plane_schema=False,
            nats=True,
            outbox_relay=True,
        )
    )
    app = create_http_app(lifecycle)  # type: ignore[arg-type]

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["checks"] == {
        "postgres": False,
        "control_plane_schema": False,
        "nats": True,
        "outbox_relay": True,
    }


@pytest.mark.asyncio
async def test_ready_succeeds_when_dependencies_are_healthy() -> None:
    lifecycle = FakeLifecycle(
        Readiness(
            postgres=True,
            control_plane_schema=True,
            nats=True,
            outbox_relay=True,
        )
    )
    app = create_http_app(lifecycle)  # type: ignore[arg-type]

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ready_rejects_incompatible_control_plane_schema() -> None:
    lifecycle = FakeLifecycle(
        Readiness(
            postgres=True,
            control_plane_schema=False,
            nats=True,
            outbox_relay=True,
        )
    )
    app = create_http_app(lifecycle)  # type: ignore[arg-type]

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["checks"] == {
        "postgres": True,
        "control_plane_schema": False,
        "nats": True,
        "outbox_relay": True,
    }


@pytest.mark.asyncio
async def test_readiness_converts_dependency_exceptions_to_unavailable() -> None:
    class Dependency:
        async def ping(self) -> None:
            raise RuntimeError("unavailable")

    relay = type("Relay", (), {"ready": True})()
    lifecycle = ServiceLifecycle(Dependency(), Dependency(), relay)  # type: ignore[arg-type]
    lifecycle.state = LifecycleState.READY

    assert await lifecycle.readiness() == Readiness(
        postgres=False, control_plane_schema=False, nats=False, outbox_relay=True
    )


@pytest.mark.asyncio
async def test_readiness_bounds_dependency_ping(monkeypatch) -> None:
    class Dependency:
        async def ping(self) -> None:
            await asyncio.sleep(1)

    monkeypatch.setattr(lifecycle_module, "READINESS_TIMEOUT_SECONDS", 0.001)
    relay = type("Relay", (), {"ready": True})()
    lifecycle = ServiceLifecycle(Dependency(), Dependency(), relay)  # type: ignore[arg-type]
    lifecycle.state = LifecycleState.READY

    assert await lifecycle.readiness() == Readiness(
        postgres=False, control_plane_schema=False, nats=False, outbox_relay=True
    )


@pytest.mark.asyncio
async def test_lifecycle_starts_and_stops_dependencies_in_order() -> None:
    calls: list[str] = []

    class Database:
        async def connect(self) -> None:
            calls.append("database.connect")

        async def ping(self) -> None:
            calls.append("database.ping")

        async def schema_compatible(self) -> bool:
            calls.append("database.schema_compatible")
            return True

        async def close(self) -> None:
            calls.append("database.close")

    class Nats:
        async def connect(self) -> None:
            calls.append("nats.connect")

        async def ping(self) -> None:
            calls.append("nats.ping")

        async def drain(self) -> None:
            calls.append("nats.drain")

        async def close(self) -> None:
            calls.append("nats.close")

    class Relay:
        ready = True

        async def start(self) -> None:
            calls.append("relay.start")

        async def stop(self) -> None:
            calls.append("relay.stop")

    lifecycle = ServiceLifecycle(Database(), Nats(), Relay())

    await lifecycle.start()
    assert lifecycle.state == LifecycleState.READY
    assert (await lifecycle.readiness()).ready
    await lifecycle.stop()
    await lifecycle.stop()

    assert lifecycle.state == LifecycleState.STOPPED
    assert calls == [
        "database.connect",
        "database.schema_compatible",
        "nats.connect",
        "relay.start",
        "database.ping",
        "database.schema_compatible",
        "nats.ping",
        "relay.stop",
        "nats.drain",
        "nats.close",
        "database.close",
    ]


@pytest.mark.asyncio
async def test_lifecycle_cleans_up_database_when_nats_start_fails() -> None:
    calls: list[str] = []

    class Database:
        async def connect(self) -> None:
            calls.append("database.connect")

        async def ping(self) -> None:
            pass

        async def schema_compatible(self) -> bool:
            calls.append("database.schema_compatible")
            return True

        async def close(self) -> None:
            calls.append("database.close")

    class Nats:
        async def connect(self) -> None:
            calls.append("nats.connect")
            raise RuntimeError("nats unavailable")

        async def ping(self) -> None:
            pass

        async def drain(self) -> None:
            pass

        async def close(self) -> None:
            calls.append("nats.close")

    class Relay:
        ready = False

        async def start(self) -> None:
            calls.append("relay.start")

        async def stop(self) -> None:
            calls.append("relay.stop")

    lifecycle = ServiceLifecycle(Database(), Nats(), Relay())

    with pytest.raises(RuntimeError, match="nats unavailable"):
        await lifecycle.start()

    assert lifecycle.state == LifecycleState.STOPPED
    assert calls == [
        "database.connect",
        "database.schema_compatible",
        "nats.connect",
        "relay.stop",
        "nats.close",
        "database.close",
    ]
