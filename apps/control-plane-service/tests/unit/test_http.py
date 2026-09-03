import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

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
async def test_phone_number_assignments_do_not_have_an_update_route() -> None:
    app = create_http_app(
        FakeLifecycle(
            Readiness(
                postgres=True,
                control_plane_schema=True,
                nats=True,
                outbox_relay=True,
            )
        ),
        managed_resources=object(),  # type: ignore[arg-type]
    )
    app.state.settings = SimpleNamespace(
        control_plane_management_token=SimpleNamespace(
            get_secret_value=lambda: "management-secret"
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        phone_response = await client.put(
            "/v1/managed-resources/phone-number-assignments/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": "Bearer management-secret"},
            json={
                "phone_number": "+421552301401",
                "expected_generation": 1,
                "actor": "admin",
            },
        )
        tenant_response = await client.put(
            "/v1/managed-resources/phone-number-assignments/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": "Bearer management-secret"},
            json={"tenant_id": "tenant-b", "expected_generation": 1, "actor": "admin"},
        )

    assert phone_response.status_code == tenant_response.status_code == 405


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
async def test_management_routes_require_the_separate_management_token() -> None:
    app = create_http_app(
        FakeLifecycle(
            Readiness(
                postgres=True,
                control_plane_schema=True,
                nats=True,
                outbox_relay=True,
            )
        ),
        managed_resources=object(),  # type: ignore[arg-type]
    )
    app.state.settings = SimpleNamespace(
        control_plane_management_token=SimpleNamespace(
            get_secret_value=lambda: "management-secret"
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get("/v1/managed-resources/credentials")
        invalid = await client.get(
            "/v1/managed-resources/credentials",
            headers={"Authorization": "Bearer wrong"},
        )
        valid = await client.post(
            "/v1/managed-resources/credentials",
            headers={"Authorization": "Bearer management-secret"},
        )
    assert missing.status_code == invalid.status_code == 401
    assert valid.status_code == 422


@pytest.mark.asyncio
async def test_management_actor_is_server_derived() -> None:
    seen: list[str] = []

    class Components:
        async def save_draft(self, _address, _value, _schema, _draft, _active, actor):
            seen.append(actor)
            return {}

    app = create_http_app(FakeLifecycle(Readiness(True, True, True, True)), Components())  # type: ignore[arg-type]
    app.state.settings = SimpleNamespace(
        control_plane_management_token=SimpleNamespace(
            get_secret_value=lambda: "management-secret"
        ),
        control_plane_management_actor="agentctl",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/v1/scopes/platform/components/prompt.system/draft",
            headers={"Authorization": "Bearer management-secret"},
            json={
                "value": {"content": "hello"},
                "schema_version": 1,
                "expected_draft_version": None,
                "expected_active_revision_id": None,
                "actor": "forged",
            },
        )
    assert response.status_code == 200
    assert seen == ["agentctl"]


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
