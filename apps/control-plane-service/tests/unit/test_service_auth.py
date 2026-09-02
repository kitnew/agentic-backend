from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import jwt
import pytest
from control_plane.application.execution_materialization import (
    RuntimeSecretMaterial,
    RuntimeSecretSlot,
)
from control_plane.interfaces.http import create_http_app
from httpx import ASGITransport, AsyncClient


class Lifecycle:
    @asynccontextmanager
    async def lifespan(self, _app):
        yield


class Materializer:
    async def runtime_secret(
        self, snapshot_id: UUID, slot: RuntimeSecretSlot
    ) -> RuntimeSecretMaterial:
        return RuntimeSecretMaterial(
            snapshot_id,
            slot,
            "marker-secret",
            UUID(int=3),
            1,
            UUID(int=4),
            1,
            UUID(int=5),
            1,
            UUID(int=6),
            1,
        )


def token(service: str, secret: str, scopes: list[str], **claims: object) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "service": service,
            "sub": "consumer",
            "aud": "control-plane-service",
            "iat": now,
            "exp": now + timedelta(minutes=1),
            "scopes": scopes,
            **claims,
        },
        secret,
        algorithm="HS256",
    )


def app():
    result = create_http_app(Lifecycle(), execution_materialization=Materializer())  # type: ignore[arg-type]
    result.state.settings = SimpleNamespace(
        voice_agent_service_secret=SimpleNamespace(get_secret_value=lambda: "v" * 32),
        job_worker_service_secret=SimpleNamespace(get_secret_value=lambda: "w" * 32),
    )
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("authorization", "expected"),
    [
        (None, 401),
        ("Bearer invalid", 401),
        (
            "Bearer " + token("voice-agent", "x" * 32, ["runtime-secret:materialize"]),
            401,
        ),
        (
            "Bearer "
            + token(
                "voice-agent",
                "v" * 32,
                ["runtime-secret:materialize"],
                exp=datetime.now(UTC) - timedelta(minutes=1),
            ),
            401,
        ),
        (
            "Bearer "
            + token(
                "voice-agent",
                "v" * 32,
                ["runtime-secret:materialize"],
                aud="wrong",
            ),
            401,
        ),
        ("Bearer " + token("voice-agent", "v" * 32, []), 403),
        (
            "Bearer " + token("job-worker", "w" * 32, ["integration-material:read"]),
            403,
        ),
        (
            "Bearer "
            + token(
                "voice-agent",
                "v" * 32,
                ["runtime-secret:materialize", "integration-material:read"],
            ),
            401,
        ),
        (
            "Bearer " + token("voice-agent", "v" * 32, ["runtime-secret:materialize"]),
            200,
        ),
    ],
    ids=[
        "missing",
        "invalid",
        "bad-signature",
        "expired",
        "wrong-audience",
        "missing-scope",
        "wrong-service",
        "disallowed-scope",
        "valid",
    ],
)
async def test_runtime_materialization_requires_expected_signed_service_scope(
    authorization: str | None, expected: int
) -> None:
    headers = {"Authorization": authorization} if authorization else {}
    async with AsyncClient(
        transport=ASGITransport(app=app()), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/v1/execution-snapshots/00000000-0000-0000-0000-000000000001/secrets/llm",
            headers=headers,
        )
    assert response.status_code == expected
    if expected == 200:
        assert response.json()["secret"] == "marker-secret"
        assert response.headers["cache-control"] == "no-store"
