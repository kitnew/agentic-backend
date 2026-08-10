from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.calls.models import CallChannel, CallDirection, CallSession
from backend_core.modules.tenants.models import Tenant
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from prompt_fixtures import publish_config, publish_prompt_set, tenant_config_v3
from runtime_fixtures import (
    apply_voice_runtime,
    ensure_platform_runtime,
    platform_runtime_policy,
)
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from test_voice_test_sessions import cleanup_tenants


async def create_runtime_tenant(client: AsyncClient, slug: str) -> str:
    tenant = await client.post(
        "/admin/v1/tenants",
        json={"slug": slug, "display_name": slug, "business_type": "hotel"},
    )
    assert tenant.status_code == 201
    tenant_id = tenant.json()["id"]
    await publish_prompt_set(client, tenant_id)
    await publish_config(client, tenant_id, greeting="Dobrý deň")
    return tenant_id


@pytest.mark.asyncio
async def test_voice_runtime_authoring_resolution_and_linear_history(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings=app_settings, database=database)
    tenant_id: str | None = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            await ensure_platform_runtime(client)
            tenant_id = await create_runtime_tenant(client, "voice-runtime-hotel")

            missing_runtime_call = await client.post(
                "/admin/v1/voice/test-sessions", json={"tenant_id": tenant_id}
            )
            assert missing_runtime_call.status_code == 409
            assert missing_runtime_call.json()["detail"]["code"] == (
                "tenant_configuration_not_voice_ready"
            )

            plan_url = f"/admin/v1/tenants/{tenant_id}/voice-runtime/plan"
            history_url = f"/admin/v1/tenants/{tenant_id}/voice-runtime/revisions"
            initial_plan = await client.get(plan_url)
            assert initial_plan.status_code == 200
            assert initial_plan.json()["status"] == "missing-active"
            assert (await client.get(history_url)).json() == []

            first = await apply_voice_runtime(client, tenant_id)
            assert first["revision_number"] == 1
            assert first["effective_settings"]["tts"]["voice_id"] == "voice-a"
            assert (await client.get(plan_url)).json()["status"] == "unchanged"

            drafts_url = f"/admin/v1/tenants/{tenant_id}/runtime/drafts"
            override = await client.post(
                drafts_url, json={"settings": {"tts": {"voice_id": "voice-b"}}}
            )
            assert override.status_code == 201
            published = await client.post(
                f"{drafts_url}/{override.json()['id']}/publish"
            )
            assert published.status_code == 200
            assert (await client.get(history_url)).json()[-1]["id"] == first["id"]

            changed_plan = await client.get(plan_url)
            assert changed_plan.json()["status"] == "modified"
            assert changed_plan.json()["changes"] == [
                {"path": "tts.voice_id", "before": "voice-a", "after": "voice-b"}
            ]
            second = await apply_voice_runtime(client, tenant_id)
            assert second["revision_number"] == 2
            assert second["effective_settings"]["tts"]["voice_id"] == "voice-b"

            reset = await client.post(drafts_url, json={"settings": {}})
            assert reset.status_code == 201
            assert (
                await client.post(f"{drafts_url}/{reset.json()['id']}/publish")
            ).status_code == 200
            third = await apply_voice_runtime(client, tenant_id)
            assert third["revision_number"] == 3
            assert third["effective_settings"]["tts"]["voice_id"] == "voice-a"
            assert [
                item["revision_number"] for item in (await client.get(history_url)).json()
            ] == [1, 2, 3]
    finally:
        await cleanup_tenants(database, "voice-runtime-hotel")
        await database.close()


@pytest.mark.asyncio
async def test_runtime_publication_and_apply_are_serialized(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings=app_settings, database=database)
    tenant_id: str | None = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            await ensure_platform_runtime(client)
            tenant_id = await create_runtime_tenant(client, "runtime-lock-hotel")
            first = await apply_voice_runtime(client, tenant_id)
            runtime_drafts = f"/admin/v1/tenants/{tenant_id}/runtime/drafts"

            platform_draft = await client.post(
                "/admin/v1/platform/runtime/drafts",
                json={"policy": platform_runtime_policy()},
            )
            tenant_draft = await client.post(
                runtime_drafts,
                json={"settings": {"tts": {"voice_id": "voice-b"}}},
            )
            assert platform_draft.status_code == tenant_draft.status_code == 201
            platform_publish, tenant_publish = await asyncio.gather(
                client.post(
                    "/admin/v1/platform/runtime/drafts/"
                    f"{platform_draft.json()['id']}/publish"
                ),
                client.post(f"{runtime_drafts}/{tenant_draft.json()['id']}/publish"),
            )
            assert platform_publish.status_code == tenant_publish.status_code == 200
            active = await client.get(
                f"/admin/v1/tenants/{tenant_id}/voice-runtime"
            )
            assert active.json()["id"] == first["id"]

            second = await apply_voice_runtime(client, tenant_id)
            assert second["revision_number"] == 2
            assert second["effective_settings"]["tts"]["voice_id"] == "voice-b"

            config_draft = await client.post(
                f"/admin/v1/tenants/{tenant_id}/config/drafts",
                json={
                    "schema_version": 3,
                    "config": tenant_config_v3(greeting="Changed business greeting"),
                },
            )
            assert config_draft.status_code == 201
            config_publish, unchanged_apply = await asyncio.gather(
                client.post(
                    f"/admin/v1/tenants/{tenant_id}/config/drafts/"
                    f"{config_draft.json()['id']}/publish"
                ),
                client.post(f"/admin/v1/tenants/{tenant_id}/voice-runtime/apply"),
            )
            assert config_publish.status_code == unchanged_apply.status_code == 200

            next_override = await client.post(
                runtime_drafts,
                json={"settings": {"tts": {"voice_id": "voice-c"}}},
            )
            assert next_override.status_code == 201
            tenant_publish, racing_apply = await asyncio.gather(
                client.post(
                    f"{runtime_drafts}/{next_override.json()['id']}/publish"
                ),
                client.post(f"/admin/v1/tenants/{tenant_id}/voice-runtime/apply"),
            )
            assert tenant_publish.status_code == racing_apply.status_code == 200
            converged = await apply_voice_runtime(client, tenant_id)
            assert converged["effective_settings"]["tts"]["voice_id"] == "voice-c"

            final_override = await client.post(
                runtime_drafts,
                json={"settings": {"tts": {"voice_id": "voice-d"}}},
            )
            assert final_override.status_code == 201
            assert (
                await client.post(
                    f"{runtime_drafts}/{final_override.json()['id']}/publish"
                )
            ).status_code == 200
            applies = await asyncio.gather(
                client.post(f"/admin/v1/tenants/{tenant_id}/voice-runtime/apply"),
                client.post(f"/admin/v1/tenants/{tenant_id}/voice-runtime/apply"),
            )
            assert [response.status_code for response in applies] == [200, 200]
            assert sorted(response.json()["changed"] for response in applies) == [
                False,
                True,
            ]
    finally:
        await cleanup_tenants(database, "runtime-lock-hotel")
        await database.close()


@pytest.mark.asyncio
async def test_runtime_active_pointer_and_call_pin_are_tenant_safe(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings=app_settings, database=database)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            first_tenant = await create_runtime_tenant(client, "runtime-owner-a")
            first_runtime = await apply_voice_runtime(client, first_tenant)
            second_tenant = await create_runtime_tenant(client, "runtime-owner-b")
            await apply_voice_runtime(client, second_tenant)
            second_tenant_id = UUID(second_tenant)
            first_runtime_id = UUID(first_runtime["id"])

        with pytest.raises(IntegrityError):
            async with database.transaction() as session:
                await session.execute(
                    update(Tenant)
                    .where(Tenant.id == second_tenant_id)
                    .values(active_voice_runtime_revision_id=first_runtime_id)
                )

        with pytest.raises(IntegrityError):
            async with database.transaction() as session:
                tenant = await session.get(Tenant, second_tenant_id)
                assert tenant is not None
                assert tenant.active_config_revision_id is not None
                assert tenant.active_prompt_set_revision_id is not None
                session.add(
                    CallSession(
                        tenant_id=tenant.id,
                        tenant_config_revision_id=tenant.active_config_revision_id,
                        prompt_set_revision_id=tenant.active_prompt_set_revision_id,
                        voice_runtime_revision_id=first_runtime_id,
                        channel=CallChannel.WEB,
                        direction=CallDirection.INBOUND,
                        provider="tenant-safety-test",
                        provider_call_id="cross-tenant-runtime",
                        room_name="cross-tenant-runtime",
                    )
                )
                await session.flush()
    finally:
        await cleanup_tenants(database, "runtime-owner-a", "runtime-owner-b")
        await database.close()
