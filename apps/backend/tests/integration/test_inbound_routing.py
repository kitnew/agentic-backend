from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.tenants.models import InboundRoute, Tenant, TenantStatus
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError


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


async def create_tenant(
    client: AsyncClient,
    slug: str,
    *,
    publish_config: bool = False,
) -> dict[str, object]:
    response = await client.post(
        "/admin/v1/tenants",
        json={
            "slug": slug,
            "display_name": slug.replace("-", " ").title(),
            "business_type": "hotel",
        },
    )
    assert response.status_code == 201
    tenant = response.json()
    if publish_config:
        drafts_url = f"/admin/v1/tenants/{tenant['id']}/config/drafts"
        draft = await client.post(drafts_url, json={"config": config_v1()})
        assert draft.status_code == 201
        published = await client.post(
            f"{drafts_url}/{draft.json()['id']}/publish"
        )
        assert published.status_code == 200
        tenant["active_revision"] = published.json()
    return tenant


@pytest.mark.asyncio
async def test_inbound_route_management_and_resolution(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
    service_token: Callable[..., str],
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings=app_settings, database=database)
    transport = ASGITransport(app=app)
    voice_token = service_token(
        service="voice-agent",
        scopes=["tenant-routing:resolve"],
        secret=app_settings.voice_agent_service_secret.get_secret_value(),
    )
    worker_token = service_token(
        service="job-worker",
        scopes=["capability-result:write"],
        secret=app_settings.job_worker_service_secret.get_secret_value(),
    )
    voice_headers = {"Authorization": f"Bearer {voice_token}"}
    worker_headers = {"Authorization": f"Bearer {worker_token}"}

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            tenant = await create_tenant(
                client,
                "inbound-route-hotel",
                publish_config=True,
            )
            tenant_id = UUID(str(tenant["id"]))
            routes_url = f"/admin/v1/tenants/{tenant_id}/inbound-routes"

            invalid_did = await client.post(
                routes_url,
                json={"normalized_did": "00421552301299"},
            )
            assert invalid_did.status_code == 422

            created_response = await client.post(
                routes_url,
                json={"normalized_did": "+421552301299"},
            )
            assert created_response.status_code == 201
            route = created_response.json()
            route_id = route["id"]
            assert route["tenant_id"] == str(tenant_id)
            assert route["normalized_did"] == "+421552301299"
            assert route["enabled"] is True
            assert (await client.get(routes_url)).json() == [route]

            resolve_url = "/internal/v1/tenant-routing/resolve"
            payload = {"channel": "sip", "called_number": "+421552301299"}
            assert (
                await client.post(resolve_url, json=payload, headers=worker_headers)
            ).status_code == 403
            resolution = await client.post(
                resolve_url,
                json=payload,
                headers=voice_headers,
            )
            assert resolution.status_code == 200
            active_revision = tenant["active_revision"]
            assert isinstance(active_revision, dict)
            assert resolution.json() == {
                "tenant_id": str(tenant_id),
                "tenant_slug": "inbound-route-hotel",
                "active_config_revision_id": active_revision["id"],
                "active_config_revision_number": 1,
            }

            changed = await client.patch(
                f"{routes_url}/{route_id}",
                json={"normalized_did": "+421552301300"},
            )
            assert changed.status_code == 200
            assert changed.json()["normalized_did"] == "+421552301300"
            assert (
                await client.post(resolve_url, json=payload, headers=voice_headers)
            ).status_code == 404
            payload["called_number"] = "+421552301300"
            assert (
                await client.post(resolve_url, json=payload, headers=voice_headers)
            ).status_code == 200

            disabled = await client.patch(
                f"{routes_url}/{route_id}",
                json={"enabled": False},
            )
            assert disabled.status_code == 200
            assert disabled.json()["enabled"] is False
            assert (
                await client.post(resolve_url, json=payload, headers=voice_headers)
            ).status_code == 404
            assert (
                await client.patch(
                    f"{routes_url}/{route_id}",
                    json={"enabled": True},
                )
            ).status_code == 200

            for tenant_status in (TenantStatus.SUSPENDED, TenantStatus.ARCHIVED):
                async with database.transaction() as session:
                    await session.execute(
                        update(Tenant)
                        .where(Tenant.id == tenant_id)
                        .values(status=tenant_status)
                    )
                assert (
                    await client.post(
                        resolve_url,
                        json=payload,
                        headers=voice_headers,
                    )
                ).status_code == 404

            other_tenant = await create_tenant(client, "other-inbound-hotel")
            other_tenant_id = other_tenant["id"]
            duplicate = await client.post(
                f"/admin/v1/tenants/{other_tenant_id}/inbound-routes",
                json={"normalized_did": "+421552301300"},
            )
            assert duplicate.status_code == 409
            assert (
                await client.patch(
                    f"/admin/v1/tenants/{other_tenant_id}/inbound-routes/{route_id}",
                    json={"enabled": False},
                )
            ).status_code == 404

            route_without_config = await client.post(
                f"/admin/v1/tenants/{other_tenant_id}/inbound-routes",
                json={"normalized_did": "+421552301301"},
            )
            assert route_without_config.status_code == 201
            assert (
                await client.post(
                    resolve_url,
                    json={"channel": "sip", "called_number": "+421552301301"},
                    headers=voice_headers,
                )
            ).status_code == 404
            assert (
                await client.post(
                    resolve_url,
                    json={"channel": "whatsapp", "called_number": "+421552301301"},
                    headers=voice_headers,
                )
            ).status_code == 422

            with pytest.raises(IntegrityError):
                async with database.transaction() as session:
                    session.add(
                        InboundRoute(
                            tenant_id=UUID(str(other_tenant_id)),
                            normalized_did="421552301302",
                        )
                    )
                    await session.flush()

            assert (
                await client.post(
                    f"/admin/v1/tenants/{uuid4()}/inbound-routes",
                    json={"normalized_did": "+421552301303"},
                )
            ).status_code == 404
    finally:
        await database.close()
