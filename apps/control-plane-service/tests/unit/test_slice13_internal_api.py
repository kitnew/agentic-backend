from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import jwt
import pytest
from control_plane.application.execution_materialization import RuntimeSecretSlot
from control_plane.domain.managed_resource_errors import (
    ManagedResourceConflict,
    ManagedResourceNotFound,
)
from control_plane.interfaces.http import create_http_app
from httpx import ASGITransport, AsyncClient


class Lifecycle:
    @asynccontextmanager
    async def lifespan(self, _app):
        yield


@dataclass(frozen=True)
class Value:
    execution_id: UUID = field(default_factory=lambda: UUID(int=1))
    tenant_id: str = "tenant-a"
    architecture: str = "cascade"
    backend_actions: dict[str, object] | None = None
    handoff: tuple[object, ...] = ()
    metadata: dict[str, object] | None = None


class Materializer:
    async def create_execution(self, tenant_id, context, *, principal, idempotency_key):
        return Value(tenant_id=tenant_id, backend_actions={}, metadata=context or {})

    async def voice_context(self, execution_id):
        if execution_id == UUID(int=0):
            raise ManagedResourceNotFound("execution not found")
        return {
            "execution_id": execution_id,
            "tenant": {"locale": "en-US", "timezone": "UTC"},
            "agent": {"name": "Agent", "personality": "default", "greeting": "Hi"},
            "architecture": "cascade",
            "prompts": {"system": "s", "profile": "", "tenant": "", "knowledge": ""},
            "runtime": {"stt": {}, "llm": {}, "tts": {}, "realtime": None},
            "actions": [],
            "handoff": [],
        }

    async def worker_context(self, execution_id, action_key):
        if action_key == "unknown":
            raise ManagedResourceNotFound("execution action not found")
        return {
            "execution_id": execution_id,
            "tenant_id": "tenant-a",
            "action": {
                "key": action_key,
                "phase": "runtime",
                "definition": {},
                "execution_plan": {},
            },
            "integration": {"semantic_key": "booking"},
        }

    async def runtime_secret(self, execution_id, slot: RuntimeSecretSlot):
        return {"slot": slot, "secret": "marker-secret"}

    async def integration_material(self, execution_id, integration_key):
        if integration_key == "other":
            raise ManagedResourceNotFound("execution integration not found")
        if integration_key == "disabled":
            raise ManagedResourceConflict("integration is disabled")
        return {
            "integration_kind": "http",
            "config": {"endpoint": "https://example.com"},
            "secret": "marker-secret",
        }

    async def handoff_material(self, execution_id, destination_key):
        if destination_key == "other":
            raise ManagedResourceNotFound("execution handoff destination not found")
        return {"destination_key": destination_key, "phone_number": "+421900123456"}


class Telephony:
    async def resolve_inbound(self, phone_number):
        return {
            "tenant_id": "tenant-a",
            "phone_number": phone_number,
            "route_version": "opaque",
        }


def token(service: str, scopes: list[str], secret: str | None = None) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "service": service,
            "sub": service,
            "aud": "control-plane-service",
            "iat": now,
            "exp": now + timedelta(minutes=1),
            "scopes": scopes,
        },
        secret
        or ({"backend-core": "b" * 32, "voice-agent": "v" * 32}.get(service, "w" * 32)),
        algorithm="HS256",
    )


def app():
    result = create_http_app(
        Lifecycle(),
        execution_materialization=Materializer(),  # type: ignore[arg-type]
        telephony=Telephony(),  # type: ignore[arg-type]
    )
    result.state.settings = SimpleNamespace(
        backend_core_service_secret=SimpleNamespace(get_secret_value=lambda: "b" * 32),
        voice_agent_service_secret=SimpleNamespace(get_secret_value=lambda: "v" * 32),
    )
    return result


TARGET = {
    ("POST", "/internal/v1/executions"),
    ("GET", "/internal/v1/executions/{execution_id}/voice-context"),
    ("GET", "/internal/v1/executions/{execution_id}/worker-context"),
    ("POST", "/internal/v1/executions/{execution_id}/secrets/{slot}"),
    (
        "POST",
        "/internal/v1/executions/{execution_id}/integrations/{integration_key}/material",
    ),
    (
        "POST",
        "/internal/v1/executions/{execution_id}/handoff/{destination_key}/material",
    ),
    ("GET", "/internal/v1/telephony/inbound-route"),
}


def test_only_frozen_internal_routes_are_mounted() -> None:
    schema = app().openapi()
    routes = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        if path.startswith("/internal/v1/")
        for method in operations
    }
    assert routes == TARGET
    encoded = str(schema)
    assert "BackendExecutionContext" in encoded
    assert "VoiceExecutionContext" in encoded
    assert "WorkerExecutionContext" in encoded
    assert "ExecutionSnapshot" not in encoded
    assert "RuntimeIntegrationMaterial" not in encoded
    assert all(
        operation["security"] == [{"InternalServiceToken": []}]
        for path, operations in schema["paths"].items()
        if path.startswith("/internal/v1/")
        for operation in operations.values()
    )


@pytest.mark.asyncio
async def test_backend_and_voice_authorization_matrix_and_secret_headers() -> None:
    backend = {
        "Authorization": "Bearer " + token("backend-core", ["execution:create"]),
        "Idempotency-Key": "one",
    }
    voice = {
        "Authorization": "Bearer "
        + token("voice-agent", ["runtime-secret:materialize"])
    }
    worker = {
        "Authorization": "Bearer " + token("job-worker", ["integration-material:read"])
    }
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        created = await client.post(
            "/internal/v1/executions", headers=backend, json={"tenant_id": "tenant-a"}
        )
        voice_create = await client.post(
            "/internal/v1/executions", headers=voice, json={"tenant_id": "tenant-a"}
        )
        secret = await client.post(
            "/internal/v1/executions/00000000-0000-0000-0000-000000000001/secrets/llm",
            headers=voice,
        )
        worker_material = await client.post(
            "/internal/v1/executions/00000000-0000-0000-0000-000000000001/integrations/booking/material",
            headers=worker,
        )
    assert created.status_code == 201
    assert voice_create.status_code == 403
    assert worker_material.status_code == 401
    assert secret.status_code == 200
    assert {
        name: secret.headers[name]
        for name in ("cache-control", "pragma", "x-content-type-options")
    } == {
        "cache-control": "no-store",
        "pragma": "no-cache",
        "x-content-type-options": "nosniff",
    }
    assert secret.json() == {"slot": "llm", "secret": "marker-secret"}


@pytest.mark.asyncio
async def test_internal_errors_use_shared_envelope() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        semantic = await client.post(
            "/internal/v1/executions",
            headers={
                "Authorization": "Bearer "
                + token("backend-core", ["execution:create"]),
                "Idempotency-Key": "one",
            },
            json={"tenant_id": "tenant-a", "unexpected": True},
        )
        malformed = await client.post(
            "/internal/v1/executions",
            headers={
                "Authorization": "Bearer "
                + token("backend-core", ["execution:create"]),
                "Idempotency-Key": "two",
                "Content-Type": "application/json",
            },
            content=b"{",
        )
    assert semantic.status_code == 422
    assert malformed.status_code == 400
    assert set(semantic.json()) == {"code", "message", "issues", "request_id"}
    assert set(malformed.json()) == {"code", "message", "issues", "request_id"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/internal/v1/executions"),
        (
            "get",
            "/internal/v1/executions/00000000-0000-0000-0000-000000000001/voice-context",
        ),
        (
            "get",
            "/internal/v1/executions/00000000-0000-0000-0000-000000000001/worker-context?action_key=booking",
        ),
        (
            "post",
            "/internal/v1/executions/00000000-0000-0000-0000-000000000001/integrations/booking/material",
        ),
        (
            "post",
            "/internal/v1/executions/00000000-0000-0000-0000-000000000001/handoff/reception/material",
        ),
        ("get", "/internal/v1/telephony/inbound-route?phone_number=%2B421900123456"),
    ],
)
async def test_voice_is_rejected_from_every_non_secret_internal_route(
    method: str, path: str
) -> None:
    headers = {
        "Authorization": "Bearer "
        + token("voice-agent", ["runtime-secret:materialize"]),
        "Idempotency-Key": "one",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        response = await client.request(
            method,
            path,
            headers=headers,
            json={"tenant_id": "tenant-a"} if path.endswith("executions") else None,
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_backend_and_management_credentials_cannot_materialize_runtime_secrets() -> (
    None
):
    path = "/internal/v1/executions/00000000-0000-0000-0000-000000000001/secrets/llm"
    backend = token("backend-core", ["execution:create"])
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        backend_response = await client.post(
            path, headers={"Authorization": f"Bearer {backend}"}
        )
        management_response = await client.post(
            path, headers={"Authorization": "Bearer management-token"}
        )
    assert backend_response.status_code == 403
    assert management_response.status_code == 401


@pytest.mark.asyncio
async def test_internal_domain_errors_and_all_material_cache_headers() -> None:
    backend = {
        "Authorization": "Bearer "
        + token(
            "backend-core",
            [
                "execution:voice-context:read",
                "execution:worker-context:read",
                "integration-material:read",
                "handoff-material:read",
                "telephony:resolve",
            ],
        )
    }
    execution = "00000000-0000-0000-0000-000000000001"
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        unknown_execution = await client.get(
            "/internal/v1/executions/00000000-0000-0000-0000-000000000000/voice-context",
            headers=backend,
        )
        unknown_action = await client.get(
            f"/internal/v1/executions/{execution}/worker-context?action_key=unknown",
            headers=backend,
        )
        invalid_slot = await client.post(
            f"/internal/v1/executions/{execution}/secrets/invalid",
            headers={
                "Authorization": "Bearer "
                + token("voice-agent", ["runtime-secret:materialize"])
            },
        )
        unknown_integration = await client.post(
            f"/internal/v1/executions/{execution}/integrations/other/material",
            headers=backend,
        )
        disabled_integration = await client.post(
            f"/internal/v1/executions/{execution}/integrations/disabled/material",
            headers=backend,
        )
        integration = await client.post(
            f"/internal/v1/executions/{execution}/integrations/booking/material",
            headers=backend,
        )
        handoff = await client.post(
            f"/internal/v1/executions/{execution}/handoff/reception/material",
            headers=backend,
        )
        inbound = await client.get(
            "/internal/v1/telephony/inbound-route?phone_number=%2B421900123456",
            headers=backend,
        )
    assert [
        unknown_execution.status_code,
        unknown_action.status_code,
        invalid_slot.status_code,
        unknown_integration.status_code,
        disabled_integration.status_code,
    ] == [404, 404, 422, 404, 409]
    assert all(
        set(response.json()) >= {"code", "message", "request_id"}
        for response in (
            unknown_execution,
            unknown_action,
            invalid_slot,
            unknown_integration,
            disabled_integration,
        )
    )
    for response in (integration, handoff):
        assert response.status_code == 200
        assert {
            name: response.headers[name]
            for name in ("cache-control", "pragma", "x-content-type-options")
        } == {
            "cache-control": "no-store",
            "pragma": "no-cache",
            "x-content-type-options": "nosniff",
        }
    assert inbound.json() == {
        "tenant_id": "tenant-a",
        "phone_number": "+421900123456",
        "route_version": "opaque",
    }
