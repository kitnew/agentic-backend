from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError


def config_v1() -> dict[str, object]:
    return {
        "schema_version": 1,
        "localization": {
            "default_locale": "sk-SK",
            "timezone": "Europe/Bratislava",
        },
        "agent": {
            "display_name": "Amélia",
            "greeting": "Dobrý deň...",
        },
        "conversation": {"scope": "property_only"},
        "capabilities": {},
    }


def test_admin_and_service_credentials_must_be_distinct() -> None:
    shared_secret = "shared-test-secret-with-at-least-32-characters"
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "database_url": "postgresql+asyncpg://postgres:postgres@db/backend",
                "admin_api_token": "separate-admin-token-with-at-least-32-characters",
                "voice_agent_service_secret": shared_secret,
                "job_worker_service_secret": shared_secret,
                "livekit_url": "ws://livekit:7880",
                "livekit_public_url": "ws://localhost:7880",
                "livekit_api_key": "test-key",
                "livekit_api_secret": "test-secret",
                "livekit_agent_name": "test-agent",
            }
        )


@pytest.mark.asyncio
async def test_admin_and_internal_access_boundaries(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
    service_token: Callable[..., str],
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings=app_settings, database=database)
    transport = ASGITransport(app=app)
    voice_secret = app_settings.voice_agent_service_secret.get_secret_value()
    worker_secret = app_settings.job_worker_service_secret.get_secret_value()

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/ready")).status_code == 200
            assert (await client.get("/admin/v1/tenants")).status_code == 401
            assert (
                await client.get(
                    "/admin/v1/tenants",
                    headers={"Authorization": "Bearer wrong-admin-token"},
                )
            ).status_code == 401

            tenant_response = await client.post(
                "/admin/v1/tenants",
                headers=admin_headers,
                json={
                    "slug": "access-boundary-hotel",
                    "display_name": "Access Boundary Hotel",
                    "business_type": "hotel",
                },
            )
            assert tenant_response.status_code == 201
            tenant_id = tenant_response.json()["id"]
            drafts_url = f"/admin/v1/tenants/{tenant_id}/config/drafts"
            assert (
                await client.get(f"/admin/v1/tenants/{tenant_id}/telephony")
            ).status_code == 401
            assert (
                await client.get("/admin/v1/platform/telephony")
            ).status_code == 401

            client_authorship = await client.post(
                drafts_url,
                headers=admin_headers,
                json={
                    "config": config_v1(),
                    "created_by": "00000000-0000-0000-0000-000000000001",
                },
            )
            assert client_authorship.status_code == 422

            draft_response = await client.post(
                drafts_url,
                headers=admin_headers,
                json={"config": config_v1()},
            )
            assert draft_response.status_code == 201
            assert draft_response.json()["created_by"] is None
            revision_id = draft_response.json()["id"]
            assert (
                await client.post(
                    f"{drafts_url}/{revision_id}/publish",
                    headers=admin_headers,
                )
            ).status_code == 200

            internal_url = f"/internal/v1/tenants/{tenant_id}/active-config"
            assert (await client.get(internal_url)).status_code == 401

            worker_token = service_token(
                service="job-worker",
                scopes=["capability-result:write"],
                secret=worker_secret,
            )
            assert (
                await client.get(
                    internal_url,
                    headers={"Authorization": f"Bearer {worker_token}"},
                )
            ).status_code == 403

            wrong_audience = service_token(
                service="voice-agent",
                scopes=["tenant-config:read"],
                secret=voice_secret,
                audience="another-service",
            )
            assert (
                await client.get(
                    internal_url,
                    headers={"Authorization": f"Bearer {wrong_audience}"},
                )
            ).status_code == 401

            now = datetime.now(UTC)
            expired = service_token(
                service="voice-agent",
                scopes=["tenant-config:read"],
                secret=voice_secret,
                issued_at=now - timedelta(minutes=2),
                expires_at=now - timedelta(minutes=1),
            )
            assert (
                await client.get(
                    internal_url,
                    headers={"Authorization": f"Bearer {expired}"},
                )
            ).status_code == 401

            wrong_credential = service_token(
                service="voice-agent",
                scopes=["tenant-config:read"],
                secret=worker_secret,
            )
            assert (
                await client.get(
                    internal_url,
                    headers={"Authorization": f"Bearer {wrong_credential}"},
                )
            ).status_code == 401

            voice_token = service_token(
                service="voice-agent",
                scopes=["tenant-config:read"],
                secret=voice_secret,
            )
            assert (
                await client.get(
                    "/admin/v1/tenants",
                    headers={"Authorization": f"Bearer {voice_token}"},
                )
            ).status_code == 401
            assert (
                await client.get(
                    "/admin/v1/platform/telephony",
                    headers={"Authorization": f"Bearer {voice_token}"},
                )
            ).status_code == 401
            assert (
                await client.get(
                    internal_url,
                    headers={"Authorization": f"Bearer {voice_token}"},
                )
            ).status_code == 200

            forged_scope_token = service_token(
                service="voice-agent",
                scopes=["tenant-config:read", "capability-result:write"],
                secret=voice_secret,
            )
            assert (
                await client.get(
                    internal_url,
                    headers={
                        "Authorization": f"Bearer {forged_scope_token}",
                    },
                )
            ).status_code == 401
    finally:
        await database.close()
