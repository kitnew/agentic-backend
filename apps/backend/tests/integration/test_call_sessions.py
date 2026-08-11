from collections.abc import Callable
from uuid import uuid4

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.calls.models import CallSession
from backend_core.modules.conversations.models import Conversation
from backend_core.modules.tenants.models import ProfilePrompt, SystemPrompt, Tenant
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from runtime_fixtures import apply_voice_runtime
from sqlalchemy import delete, select


def config_v3(*, greeting: str = "Dobrý deň...") -> dict[str, object]:
    return {
        "schema_version": 3,
        "business": {"name": "Call Session Hotel", "type": "hotel"},
        "contact": {},
        "localization": {
            "default_locale": "sk-SK",
            "timezone": "Europe/Bratislava",
        },
        "agent": {
            "display_name": "Amélia",
            "greeting": greeting,
            "profile": "call_session_hotel",
        },
        "conversation": {"scope": "property_only"},
        "capabilities": {},
    }


def config_v1() -> dict[str, object]:
    return {
        "schema_version": 1,
        "localization": {
            "default_locale": "sk-SK",
            "timezone": "Europe/Bratislava",
        },
        "agent": {"display_name": "Amélia", "greeting": "Dobrý deň..."},
        "conversation": {"scope": "property_only"},
        "capabilities": {},
    }


async def publish_text(
    client: AsyncClient, drafts_url: str, body: dict[str, str]
) -> str:
    draft = await client.post(drafts_url, json=body)
    assert draft.status_code == 201
    revision_id = draft.json()["id"]
    assert (await client.post(f"{drafts_url}/{revision_id}/publish")).status_code == 200
    return revision_id


async def prepare_voice_ready_tenant(
    client: AsyncClient,
) -> tuple[str, str, str, str]:
    tenant_response = await client.post(
        "/admin/v1/tenants",
        json={
            "slug": "call-session-hotel",
            "display_name": "Call Session Hotel",
            "business_type": "hotel",
        },
    )
    assert tenant_response.status_code == 201
    tenant_id = tenant_response.json()["id"]

    system_revision_id = await publish_text(
        client,
        "/admin/v1/platform/prompts/system/drafts",
        {"key": "call_session_system", "text": "System instructions"},
    )
    profile_revision_id = await publish_text(
        client,
        "/admin/v1/platform/prompts/profiles/drafts",
        {"key": "call_session_hotel", "text": "Hotel profile"},
    )
    tenant_revision_id = await publish_text(
        client,
        f"/admin/v1/tenants/{tenant_id}/tenant-prompt/drafts",
        {"text": "Tenant instructions"},
    )
    documents = {
        "documents": [
            {
                "key": "knowledge",
                "media_type": "text/markdown",
                "content": "Tenant facts",
            }
        ]
    }
    knowledge_plan = await client.post(
        f"/admin/v1/tenants/{tenant_id}/knowledge-base/plan", json=documents
    )
    assert knowledge_plan.status_code == 200
    assert (
        await client.post(
            f"/admin/v1/tenants/{tenant_id}/knowledge-base/push",
            json=documents,
            headers={"If-Match": f'"{knowledge_plan.json()["base_version"]}"'},
        )
    ).status_code == 200
    knowledge_published = await client.post(
        f"/admin/v1/tenants/{tenant_id}/knowledge-base/publish"
    )
    assert knowledge_published.status_code == 200
    knowledge_revision_id = knowledge_published.json()["published"]["revision"]["id"]

    config_drafts_url = f"/admin/v1/tenants/{tenant_id}/config/drafts"
    config_draft = await client.post(
        config_drafts_url,
        json={"config": config_v3()},
    )
    assert config_draft.status_code == 201
    config_revision_id = config_draft.json()["id"]
    assert (
        await client.post(f"{config_drafts_url}/{config_revision_id}/publish")
    ).status_code == 200

    prompt_set_url = f"/admin/v1/tenants/{tenant_id}/prompt-set/drafts"
    prompt_set = await client.post(
        prompt_set_url,
        json={
            "system_prompt_revision_id": system_revision_id,
            "profile_prompt_revision_id": profile_revision_id,
            "tenant_prompt_revision_id": tenant_revision_id,
            "knowledge_base_revision_id": knowledge_revision_id,
        },
    )
    assert prompt_set.status_code == 201
    prompt_set_revision_id = prompt_set.json()["id"]
    assert (
        await client.post(f"{prompt_set_url}/{prompt_set_revision_id}/publish")
    ).status_code == 200

    voice_runtime_revision_id = (await apply_voice_runtime(client, tenant_id))["id"]

    route = await client.post(
        f"/admin/v1/tenants/{tenant_id}/inbound-routes",
        json={"normalized_did": "+421552301410"},
    )
    assert route.status_code == 201
    return (
        tenant_id,
        config_revision_id,
        prompt_set_revision_id,
        voice_runtime_revision_id,
    )


@pytest.mark.asyncio
async def test_call_session_pins_revisions_and_enforces_lifecycle(
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
        scopes=[
            "call-session:create",
            "call-session:activate",
            "call-session:complete",
            "call-session:fail",
            "call-session:observe",
        ],
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
            (
                tenant_id,
                config_revision_id,
                prompt_set_revision_id,
                voice_runtime_revision_id,
            ) = await prepare_voice_ready_tenant(client)
            calls_url = "/internal/v1/call-sessions"
            payload = {
                "channel": "sip",
                "called_number": "+421552301410",
                "provider": "livekit",
                "provider_call_id": "provider-call-1",
                "room_name": "call-room-1",
            }

            assert (
                await client.post(calls_url, json=payload, headers=worker_headers)
            ).status_code == 403
            created_response = await client.post(
                calls_url,
                json=payload,
                headers=voice_headers,
            )
            assert created_response.status_code == 201
            created = created_response.json()
            call_id = created["id"]
            assert created["tenant_id"] == tenant_id
            assert created["tenant_config_revision_id"] == config_revision_id
            assert created["prompt_set_revision_id"] == prompt_set_revision_id
            assert created["voice_runtime_revision_id"] == voice_runtime_revision_id
            assert created["channel"] == "sip"
            assert created["direction"] == "inbound"
            assert created["status"] == "created"
            assert created["started_at"] is None
            assert created["ended_at"] is None
            assert created["failure_reason"] is None

            replay = await client.post(
                calls_url,
                json={**payload, "room_name": "another-room"},
                headers=voice_headers,
            )
            assert replay.status_code == 200
            assert replay.json() == created

            runtime_drafts_url = f"/admin/v1/tenants/{tenant_id}/runtime/drafts"
            runtime_draft = await client.post(
                runtime_drafts_url,
                json={"settings": {"tts": {"voice_id": "voice-b"}}},
            )
            assert runtime_draft.status_code == 201
            assert (
                await client.post(
                    f"{runtime_drafts_url}/{runtime_draft.json()['id']}/publish"
                )
            ).status_code == 200
            runtime_apply = await client.post(
                f"/admin/v1/tenants/{tenant_id}/voice-runtime/apply"
            )
            assert runtime_apply.status_code == 200
            next_voice_runtime_revision_id = runtime_apply.json()["voice_runtime"][
                "id"
            ]

            config_drafts_url = f"/admin/v1/tenants/{tenant_id}/config/drafts"
            next_config = await client.post(
                config_drafts_url,
                json={"config": config_v3(greeting="Ahoj")},
            )
            assert next_config.status_code == 201
            next_config_id = next_config.json()["id"]
            assert (
                await client.post(f"{config_drafts_url}/{next_config_id}/publish")
            ).status_code == 200

            existing_after_publish = await client.post(
                calls_url,
                json=payload,
                headers=voice_headers,
            )
            assert existing_after_publish.json()["tenant_config_revision_id"] == (
                config_revision_id
            )
            assert existing_after_publish.json()["voice_runtime_revision_id"] == (
                voice_runtime_revision_id
            )
            new_call = await client.post(
                calls_url,
                json={
                    **payload,
                    "provider_call_id": "provider-call-after-config-publish",
                    "room_name": "call-room-after-config-publish",
                },
                headers=voice_headers,
            )
            assert new_call.status_code == 201
            assert new_call.json()["tenant_config_revision_id"] == next_config_id
            assert new_call.json()["voice_runtime_revision_id"] == (
                next_voice_runtime_revision_id
            )

            started = await client.post(
                f"/internal/v1/calls/{call_id}/observations",
                headers=voice_headers,
                json={"schema_version": 1, "observation_type": "session_started"},
            )
            assert started.status_code == 200
            assert started.json()["status"] == "started"
            assert started.json()["started_at"] is not None
            assert (
                await client.post(
                    f"/internal/v1/calls/{call_id}/observations",
                    headers=voice_headers,
                    json={
                        "schema_version": 1,
                        "observation_type": "session_started",
                    },
                )
            ).json() == started.json()

            connected = await client.post(
                f"/internal/v1/calls/{call_id}/observations",
                headers=voice_headers,
                json={
                    "schema_version": 1,
                    "observation_type": "participant_connected",
                },
            )
            assert connected.status_code == 200
            assert connected.json()["status"] == "connected"
            assert connected.json()["connected_at"] is not None

            completed = await client.post(
                f"/internal/v1/calls/{call_id}/observations",
                headers=voice_headers,
                json={"schema_version": 1, "observation_type": "session_finished"},
            )
            assert completed.status_code == 200
            assert completed.json()["status"] == "ended"
            assert completed.json()["ended_at"] is not None
            assert (
                await client.post(
                    f"{calls_url}/{call_id}/fail",
                    json={"failure_reason": "late failure"},
                    headers=voice_headers,
                )
            ).status_code == 409

            failed_payload = {
                **payload,
                "provider_call_id": "provider-call-2",
                "room_name": "call-room-2",
            }
            failed_call = await client.post(
                calls_url,
                json=failed_payload,
                headers=voice_headers,
            )
            failed_call_id = failed_call.json()["id"]
            failed = await client.post(
                f"{calls_url}/{failed_call_id}/fail",
                json={"failure_reason": "provider rejected call"},
                headers=voice_headers,
            )
            assert failed.status_code == 200
            assert failed.json()["status"] == "failed"
            assert failed.json()["started_at"] is None
            assert failed.json()["ended_at"] is not None
            assert failed.json()["failure_reason"] == "provider rejected call"

            assert (
                await client.post(
                    f"{calls_url}/{uuid4()}/activate",
                    headers=voice_headers,
                )
            ).status_code == 404
            assert (
                await client.post(
                    calls_url,
                    json={
                        **payload,
                        "called_number": "+421552301499",
                        "provider_call_id": "provider-call-missing-route",
                    },
                    headers=voice_headers,
                )
            ).status_code == 404

            legacy_tenant = await client.post(
                "/admin/v1/tenants",
                json={
                    "slug": "call-session-legacy-hotel",
                    "display_name": "Call Session Legacy Hotel",
                    "business_type": "hotel",
                },
            )
            assert legacy_tenant.status_code == 201
            legacy_tenant_id = legacy_tenant.json()["id"]
            legacy_drafts_url = f"/admin/v1/tenants/{legacy_tenant_id}/config/drafts"
            legacy_draft = await client.post(
                legacy_drafts_url,
                json={"config": config_v1()},
            )
            assert legacy_draft.status_code == 201
            legacy_revision_id = legacy_draft.json()["id"]
            assert (
                await client.post(f"{legacy_drafts_url}/{legacy_revision_id}/publish")
            ).status_code == 200
            assert (
                await client.post(
                    f"/admin/v1/tenants/{legacy_tenant_id}/inbound-routes",
                    json={"normalized_did": "+421552301411"},
                )
            ).status_code == 201
            legacy_call = await client.post(
                calls_url,
                json={
                    **payload,
                    "called_number": "+421552301411",
                    "provider_call_id": "provider-call-legacy-v1",
                },
                headers=voice_headers,
            )
            assert legacy_call.status_code == 409
            assert legacy_call.json()["detail"]["code"] == (
                "tenant_configuration_not_voice_ready"
            )
    finally:
        async with database.transaction() as session:
            await session.execute(
                delete(Conversation).where(
                    Conversation.tenant_id.in_(
                        select(Tenant.id).where(
                            Tenant.slug.in_(
                                ("call-session-hotel", "call-session-legacy-hotel")
                            )
                        )
                    )
                )
            )
            await session.execute(
                delete(CallSession).where(
                    CallSession.tenant_id.in_(
                        select(Tenant.id).where(
                            Tenant.slug.in_(
                                ("call-session-hotel", "call-session-legacy-hotel")
                            )
                        )
                    )
                )
            )
            await session.execute(
                delete(Tenant).where(
                    Tenant.slug.in_(("call-session-hotel", "call-session-legacy-hotel"))
                )
            )
            await session.execute(
                delete(SystemPrompt).where(SystemPrompt.key == "call_session_system")
            )
            await session.execute(
                delete(ProfilePrompt).where(ProfilePrompt.key == "call_session_hotel")
            )
        await database.close()
