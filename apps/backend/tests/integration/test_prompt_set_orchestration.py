import asyncio
from collections.abc import Callable

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.tenants.models import ProfilePrompt, ProfilePromptRevision
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from prompt_fixtures import publish_config, publish_prompt_set, tenant_config_v3
from runtime_fixtures import apply_voice_runtime
from sqlalchemy import delete, select
from test_voice_test_sessions import cleanup_tenants


async def publish_tenant_text(
    client: AsyncClient, tenant_id: str, resource: str, text: str
) -> str:
    if resource == "knowledge-base":
        documents = {
            "documents": [
                {
                    "key": "knowledge",
                    "media_type": "text/markdown",
                    "content": text,
                }
            ]
        }
        plan = await client.post(
            f"/admin/v1/tenants/{tenant_id}/knowledge-base/plan", json=documents
        )
        assert plan.status_code == 200
        pushed = await client.post(
            f"/admin/v1/tenants/{tenant_id}/knowledge-base/push",
            json=documents,
            headers={"If-Match": f'"{plan.json()["base_version"]}"'},
        )
        assert pushed.status_code == 200
        published = await client.post(
            f"/admin/v1/tenants/{tenant_id}/knowledge-base/publish"
        )
        assert published.status_code == 200
        return published.json()["published"]["revision"]["id"]
    draft = await client.post(
        f"/admin/v1/tenants/{tenant_id}/{resource}/drafts", json={"text": text}
    )
    assert draft.status_code == 201
    published = await client.post(
        f"/admin/v1/tenants/{tenant_id}/{resource}/drafts/{draft.json()['id']}/publish"
    )
    assert published.status_code == 200
    return published.json()["id"]


async def cleanup_profile(database: Database, key: str) -> None:
    async with database.transaction() as session:
        profile_id = await session.scalar(
            select(ProfilePrompt.id).where(ProfilePrompt.key == key)
        )
        if profile_id is not None:
            await session.execute(
                delete(ProfilePromptRevision).where(
                    ProfilePromptRevision.profile_prompt_id == profile_id
                )
            )
            await session.execute(
                delete(ProfilePrompt).where(ProfilePrompt.id == profile_id)
            )


@pytest.mark.asyncio
async def test_targeted_rollout_plan_apply_and_call_pinning(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
    service_token: Callable[..., str],
) -> None:
    database = Database(migrated_database_url)
    app = create_app(settings=app_settings, database=database)
    voice_headers = {
        "Authorization": "Bearer "
        + service_token(
            service="voice-agent",
            scopes=["call-session:create"],
            secret=app_settings.voice_agent_service_secret.get_secret_value(),
        )
    }
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            tenant = await client.post(
                "/admin/v1/tenants",
                json={
                    "slug": "orchestration-hotel",
                    "display_name": "Orchestration Hotel",
                    "business_type": "hotel",
                },
            )
            tenant_id = tenant.json()["id"]
            initial = await publish_prompt_set(client, tenant_id)
            await publish_config(client, tenant_id, greeting="Hello")
            await apply_voice_runtime(client, tenant_id)
            empty_tenant = await client.post(
                "/admin/v1/tenants",
                json={
                    "slug": "orchestration-empty",
                    "display_name": "Orchestration Empty",
                    "business_type": "hotel",
                },
            )
            empty_tenant_id = empty_tenant.json()["id"]
            missing_plan = await client.get(
                f"/admin/v1/tenants/{empty_tenant_id}/prompt-set/plan"
            )
            assert missing_plan.status_code == 422
            assert missing_plan.json()["detail"]["errors"] == [
                {
                    "path": "tenant.active_config_revision_id",
                    "code": "active_config_not_found",
                    "message": "tenant has no active config",
                }
            ]

            telephony = await client.put(
                f"/admin/v1/tenants/{tenant_id}/telephony",
                json={
                    "phone_number": "+421552309901",
                    "handoff": {"destinations": {}},
                },
            )
            assert telephony.status_code == 200
            assert (
                await client.post(
                    f"/admin/v1/tenants/{tenant_id}/config/drafts/"
                    f"{telephony.json()['draft_revision_id']}/publish"
                )
            ).status_code == 200
            call_payload = {
                "channel": "sip",
                "called_number": "+421552309901",
                "provider": "livekit",
                "provider_call_id": "before-rollout",
                "room_name": "before-rollout",
            }
            call_a = await client.post(
                "/internal/v1/call-sessions",
                json=call_payload,
                headers=voice_headers,
            )
            assert call_a.status_code == 201
            assert (
                call_a.json()["prompt_set_revision_id"]
                == (initial["prompt_set_revision_id"])
            )

            newer_tenant = await publish_tenant_text(
                client, tenant_id, "tenant-prompt", "New tenant prompt"
            )
            newer_knowledge = await publish_tenant_text(
                client, tenant_id, "knowledge-base", "New knowledge"
            )
            system_draft = await client.post(
                "/admin/v1/platform/prompts/system/drafts",
                json={"key": "default", "text": "System revision two"},
            )
            system_publish = await client.post(
                "/admin/v1/platform/prompts/system/drafts/"
                f"{system_draft.json()['id']}/publish"
            )
            assert system_publish.status_code == 200
            assert system_publish.json()["rollout"] == {
                "updated_tenants": 1,
                "unchanged_tenants": 0,
            }

            rolled_out = (
                await client.get(f"/admin/v1/tenants/{tenant_id}/prompt-set/active")
            ).json()
            assert (
                rolled_out["system_prompt_revision_id"] == (system_publish.json()["id"])
            )
            assert (
                rolled_out["profile_prompt_revision_id"]
                == (initial["profile_revision_id"])
            )
            assert (
                rolled_out["tenant_prompt_revision_id"]
                == (initial["tenant_prompt_revision_id"])
            )
            assert (
                rolled_out["knowledge_base_revision_id"]
                == (initial["knowledge_base_revision_id"])
            )
            assert newer_tenant != rolled_out["tenant_prompt_revision_id"]
            assert newer_knowledge != rolled_out["knowledge_base_revision_id"]
            assert (
                await client.get(
                    f"/admin/v1/tenants/{empty_tenant_id}/prompt-set/active"
                )
            ).status_code == 404

            profile_draft = await client.post(
                "/admin/v1/platform/prompts/profiles/drafts",
                json={
                    "key": "hotel_assistant",
                    "text": "Profile revision two",
                },
            )
            profile_publish = await client.post(
                "/admin/v1/platform/prompts/profiles/drafts/"
                f"{profile_draft.json()['id']}/publish"
            )
            assert profile_publish.status_code == 200
            assert profile_publish.json()["rollout"] == {
                "updated_tenants": 1,
                "unchanged_tenants": 0,
            }
            profiled = (
                await client.get(f"/admin/v1/tenants/{tenant_id}/prompt-set/active")
            ).json()
            assert (
                profiled["profile_prompt_revision_id"] == (profile_publish.json()["id"])
            )
            assert (
                profiled["system_prompt_revision_id"]
                == (rolled_out["system_prompt_revision_id"])
            )
            assert (
                profiled["tenant_prompt_revision_id"]
                == (rolled_out["tenant_prompt_revision_id"])
            )
            assert (
                profiled["knowledge_base_revision_id"]
                == (rolled_out["knowledge_base_revision_id"])
            )
            rolled_out = profiled

            call_b = await client.post(
                "/internal/v1/call-sessions",
                json={
                    **call_payload,
                    "provider_call_id": "after-rollout",
                    "room_name": "after-rollout",
                },
                headers=voice_headers,
            )
            assert call_b.json()["prompt_set_revision_id"] == rolled_out["id"]
            replay_a = await client.post(
                "/internal/v1/call-sessions",
                json=call_payload,
                headers=voice_headers,
            )
            assert (
                replay_a.json()["prompt_set_revision_id"]
                == (initial["prompt_set_revision_id"])
            )

            plan = await client.get(f"/admin/v1/tenants/{tenant_id}/prompt-set/plan")
            assert plan.status_code == 200
            assert plan.json()["status"] == "modified"
            assert plan.json()["components"]["system"]["changed"] is False
            assert (
                plan.json()["components"]["tenant_prompt"]["desired"]["revision_id"]
                == newer_tenant
            )
            assert (
                plan.json()["components"]["knowledge_base"]["desired"]["revision_id"]
                == newer_knowledge
            )

            applied = await client.post(
                f"/admin/v1/tenants/{tenant_id}/prompt-set/apply"
            )
            assert applied.status_code == 200
            assert applied.json()["changed"] is True
            applied_revision = applied.json()["prompt_set"]["revision"]
            assert applied_revision["tenant_prompt_revision_id"] == newer_tenant
            assert applied_revision["knowledge_base_revision_id"] == newer_knowledge
            no_op = await client.post(f"/admin/v1/tenants/{tenant_id}/prompt-set/apply")
            assert no_op.json()["changed"] is False

            call_c = await client.post(
                "/internal/v1/call-sessions",
                json={
                    **call_payload,
                    "provider_call_id": "after-apply",
                    "room_name": "after-apply",
                },
                headers=voice_headers,
            )
            assert call_c.json()["prompt_set_revision_id"] == applied_revision["id"]

            alternate = await client.post(
                "/admin/v1/platform/prompts/profiles/drafts",
                json={
                    "key": "orchestration_alternate",
                    "text": "Alternate profile",
                },
            )
            alternate_publish = await client.post(
                "/admin/v1/platform/prompts/profiles/drafts/"
                f"{alternate.json()['id']}/publish"
            )
            assert alternate_publish.json()["rollout"]["updated_tenants"] == 0
            active_before_config = (
                await client.get(f"/admin/v1/tenants/{tenant_id}/prompt-set/active")
            ).json()
            config_draft = await client.post(
                f"/admin/v1/tenants/{tenant_id}/config/drafts",
                json={
                    "schema_version": 3,
                    "config": tenant_config_v3(
                        greeting="Hello alternate",
                        profile="orchestration_alternate",
                    ),
                },
            )
            config_publish = await client.post(
                f"/admin/v1/tenants/{tenant_id}/config/drafts/"
                f"{config_draft.json()['id']}/publish"
            )
            assert config_publish.status_code == 200
            active_after_config = (
                await client.get(f"/admin/v1/tenants/{tenant_id}/prompt-set/active")
            ).json()
            assert active_after_config["id"] == active_before_config["id"]
            mismatch_plan = (
                await client.get(f"/admin/v1/tenants/{tenant_id}/prompt-set/plan")
            ).json()
            assert mismatch_plan["components"]["profile"]["changed"] is True
            assert mismatch_plan["components"]["profile"]["desired"]["key"] == (
                "orchestration_alternate"
            )
            alternate_apply = await client.post(
                f"/admin/v1/tenants/{tenant_id}/prompt-set/apply"
            )
            assert alternate_apply.json()["changed"] is True
            alternate_revision = alternate_apply.json()["prompt_set"]["revision"]
            hotel_config = await client.post(
                f"/admin/v1/tenants/{tenant_id}/config/drafts",
                json={
                    "schema_version": 3,
                    "config": tenant_config_v3(
                        greeting="Hello hotel",
                        profile="hotel_assistant",
                    ),
                },
            )
            assert hotel_config.status_code == 201
            assert (
                await client.post(
                    f"/admin/v1/tenants/{tenant_id}/config/drafts/"
                    f"{hotel_config.json()['id']}/publish"
                )
            ).status_code == 200
            repeated_apply = await client.post(
                f"/admin/v1/tenants/{tenant_id}/prompt-set/apply"
            )
            assert repeated_apply.json()["changed"] is True
            repeated_revision = repeated_apply.json()["prompt_set"]["revision"]
            assert (
                repeated_revision["revision_number"]
                > alternate_revision["revision_number"]
            )
            assert repeated_revision["id"] != applied_revision["id"]
            assert (
                repeated_revision["system_prompt_revision_id"]
                == applied_revision["system_prompt_revision_id"]
            )
            assert (
                repeated_revision["profile_prompt_revision_id"]
                == applied_revision["profile_prompt_revision_id"]
            )
            assert (
                repeated_revision["tenant_prompt_revision_id"]
                == applied_revision["tenant_prompt_revision_id"]
            )
            assert (
                repeated_revision["knowledge_base_revision_id"]
                == applied_revision["knowledge_base_revision_id"]
            )
            replay_b = await client.post(
                "/internal/v1/call-sessions",
                json={
                    **call_payload,
                    "provider_call_id": "after-rollout",
                    "room_name": "after-rollout",
                },
                headers=voice_headers,
            )
            assert replay_b.json()["prompt_set_revision_id"] == rolled_out["id"]
    finally:
        await cleanup_tenants(database, "orchestration-hotel", "orchestration-empty")
        await cleanup_profile(database, "orchestration_alternate")
        await database.close()


@pytest.mark.asyncio
async def test_concurrent_system_and_profile_rollouts_preserve_both_updates(
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
            tenant = await client.post(
                "/admin/v1/tenants",
                json={
                    "slug": "concurrent-rollout-hotel",
                    "display_name": "Concurrent Rollout Hotel",
                    "business_type": "hotel",
                },
            )
            tenant_id = tenant.json()["id"]
            await publish_prompt_set(client, tenant_id)
            await publish_config(client, tenant_id, greeting="Hello")
            system = await client.post(
                "/admin/v1/platform/prompts/system/drafts",
                json={"key": "default", "text": "Concurrent system"},
            )
            profile = await client.post(
                "/admin/v1/platform/prompts/profiles/drafts",
                json={"key": "hotel_assistant", "text": "Concurrent profile"},
            )

            system_result, profile_result = await asyncio.gather(
                client.post(
                    "/admin/v1/platform/prompts/system/drafts/"
                    f"{system.json()['id']}/publish"
                ),
                client.post(
                    "/admin/v1/platform/prompts/profiles/drafts/"
                    f"{profile.json()['id']}/publish"
                ),
            )
            assert system_result.status_code == 200
            assert profile_result.status_code == 200
            active = (
                await client.get(f"/admin/v1/tenants/{tenant_id}/prompt-set/active")
            ).json()
            assert active["system_prompt_revision_id"] == system_result.json()["id"]
            assert active["profile_prompt_revision_id"] == profile_result.json()["id"]
    finally:
        await cleanup_tenants(database, "concurrent-rollout-hotel")
        await database.close()
