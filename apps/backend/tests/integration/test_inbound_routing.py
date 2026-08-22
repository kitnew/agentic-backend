from collections.abc import Callable

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.tenants.schemas import normalize_e164
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from prompt_fixtures import create_voice_ready_tenant
from test_voice_test_sessions import cleanup_tenants


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+421552301299", "+421552301299"),
        (" +421 55-230-1299 ", "+421552301299"),
        ("00421552301299", None),
        ("421552301299", None),
        ("+0421552301299", None),
    ],
)
def test_transport_phone_normalization(raw: str, expected: str | None) -> None:
    assert normalize_e164(raw) == expected


@pytest.mark.asyncio
async def test_published_telephony_routes_called_number_and_rejects_duplicates(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
    service_token: Callable[..., str],
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings=app_settings, database=database)
    transport = ASGITransport(app=app)
    token = service_token(
        service="voice-agent",
        scopes=["tenant-routing:resolve"],
        secret=app_settings.voice_agent_service_secret.get_secret_value(),
    )
    try:
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=admin_headers
        ) as client:
            tenant_id, did = await create_voice_ready_tenant(client, "routing-hotel")
            resolved = await client.post(
                "/internal/v1/tenant-routing/resolve",
                headers={"Authorization": f"Bearer {token}"},
                json={"channel": "sip", "called_number": did},
            )
            assert resolved.status_code == 200
            assert resolved.json()["tenant_id"] == tenant_id

            other_id, _ = await create_voice_ready_tenant(
                client, "other-routing-hotel"
            )
            conflict = await client.put(
                f"/admin/v1/tenants/{other_id}/telephony",
                json={"phone_number": did, "handoff": {"destinations": {}}},
            )
            assert conflict.status_code == 409
    finally:
        await cleanup_tenants(database, "routing-hotel", "other-routing-hotel")
        await database.close()
