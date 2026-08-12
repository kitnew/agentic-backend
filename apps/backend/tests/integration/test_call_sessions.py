import asyncio
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
from sqlalchemy import delete, func, select, update


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


def config_v4(*, reception: str = "+421900000001") -> dict[str, object]:
    return {
        **config_v3(),
        "schema_version": 4,
        "handoff": {
            "destinations": {
                "reception": {
                    "description": "Reservations and general reception requests",
                    "phone_number": reception,
                }
            }
        },
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
    config: dict[str, object] | None = None,
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
        json={
            "config": config or config_v3(),
            "schema_version": (config or config_v3())["schema_version"],
        },
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
            next_voice_runtime_revision_id = runtime_apply.json()["voice_runtime"]["id"]

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


@pytest.mark.asyncio
async def test_inbound_sip_claim_is_concurrent_idempotent_and_observable(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
    service_token: Callable[..., str],
) -> None:
    class LiveKit:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []
            self.fail = False

        async def create_sip_participant(
            self, *, room_name: str, participant_identity: str, phone_number: str
        ) -> tuple[str, str]:
            if self.fail:
                raise RuntimeError("provider detail")
            self.calls.append((room_name, participant_identity, phone_number))
            return participant_identity, "SCL_handoff_1"

    database = Database(migrated_database_url)
    livekit = LiveKit()
    app = create_app(settings=app_settings, database=database, livekit=livekit)  # type: ignore[arg-type]
    transport = ASGITransport(app=app)
    voice_token = service_token(
        service="voice-agent",
        scopes=[
            "call-session:inbound-sip:claim",
            "call-session:handoff",
            "call-session:observe",
        ],
        secret=app_settings.voice_agent_service_secret.get_secret_value(),
    )
    voice_headers = {"Authorization": f"Bearer {voice_token}"}
    claim_url = "/internal/v1/calls/inbound-sip/claim"
    payload = {
        "sip_call_id": "SCL_inbound_1",
        "sip_call_id_full": "telnyx-call-1@example.net",
        "trunk_id": "ST_telnyx",
        "dispatch_rule_id": "SDR_individual",
        "caller_number": "+421 900-111-222",
        "called_number": "+421 55-230-1410",
        "room_name": "sip-call-example",
        "participant_identity": "sip-caller-example",
    }
    try:
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=admin_headers
        ) as client:
            (
                tenant_id,
                config_revision_id,
                prompt_set_revision_id,
                voice_runtime_revision_id,
            ) = await prepare_voice_ready_tenant(client, config_v4())

            assert (await client.post(claim_url, json=payload)).status_code == 401
            assert (
                await client.post(
                    claim_url,
                    json={**payload, "tenant_id": tenant_id},
                    headers=voice_headers,
                )
            ).status_code == 422

            responses = await asyncio.gather(
                *(
                    client.post(claim_url, json=payload, headers=voice_headers)
                    for _ in range(4)
                )
            )
            assert sorted(response.status_code for response in responses) == [
                200,
                200,
                200,
                200,
            ]
            bodies = [response.json() for response in responses]
            call_ids = {body["call_session_id"] for body in bodies}
            assert len(call_ids) == 1
            assert sum(body["created"] for body in bodies) == 1
            call_id = call_ids.pop()

            detail = await client.get(f"/admin/v1/calls/{call_id}")
            assert detail.status_code == 200
            call = detail.json()
            assert call["tenant_id"] == tenant_id
            assert call["tenant_config_revision_id"] == config_revision_id
            assert call["prompt_set_revision_id"] == prompt_set_revision_id
            assert call["voice_runtime_revision_id"] == voice_runtime_revision_id
            assert call["caller_phone_e164"] == "+421900111222"
            assert call["called_phone_e164"] == "+421552301410"
            assert call["sip_call_id"] == "SCL_inbound_1"
            assert call["sip_call_id_full"] == "telnyx-call-1@example.net"
            assert call["sip_trunk_id"] == "ST_telnyx"
            assert call["sip_dispatch_rule_id"] == "SDR_individual"
            assert call["room_name"] == "sip-call-example"
            assert call["livekit_participant_identity"] == "sip-caller-example"

            context = await client.get(
                f"/internal/v1/calls/{call_id}/runtime-context",
                headers={
                    "Authorization": "Bearer "
                    + service_token(
                        service="voice-agent",
                        scopes=["call-session:runtime-context:read"],
                        secret=app_settings.voice_agent_service_secret.get_secret_value(),
                    )
                },
            )
            assert context.json()["handoff_destinations"] == {
                "reception": {
                    "description": "Reservations and general reception requests"
                }
            }
            assert "+421900000001" not in context.text

            config_drafts_url = f"/admin/v1/tenants/{tenant_id}/config/drafts"
            next_config = await client.post(
                config_drafts_url,
                json={
                    "config": config_v4(reception="+421900000002"),
                    "schema_version": 4,
                },
            )
            assert next_config.status_code == 201
            assert (
                await client.post(
                    f"{config_drafts_url}/{next_config.json()['id']}/publish"
                )
            ).status_code == 200

            for observation in ("session_started", "participant_connected"):
                assert (
                    await client.post(
                        f"/internal/v1/calls/{call_id}/observations",
                        json={"observation_type": observation},
                        headers=voice_headers,
                    )
                ).status_code == 200
            handoff_url = f"/internal/v1/calls/{call_id}/handoff"
            unknown = await client.post(
                handoff_url,
                json={"tool_call_id": "tool-unknown", "destination": "manager"},
                headers=voice_headers,
            )
            assert unknown.status_code == 409
            assert unknown.json()["detail"]["code"] == "unknown_destination"
            assert (
                await client.post(
                    handoff_url,
                    json={
                        "tool_call_id": "tool-extra",
                        "destination": "reception",
                        "phone_number": "+421900000099",
                    },
                    headers=voice_headers,
                )
            ).status_code == 422
            assert (
                await client.post(
                    handoff_url,
                    json={
                        "tool_call_id": "tool-cross-tenant",
                        "destination": "reception",
                        "tenant_id": str(uuid4()),
                    },
                    headers=voice_headers,
                )
            ).status_code == 422
            transfer = await client.post(
                handoff_url,
                json={
                    "tool_call_id": "tool-transfer",
                    "destination": "reception",
                    "reason": "Guest requested reception",
                },
                headers=voice_headers,
            )
            assert transfer.json() == {
                "status": "transferred",
                "destination": "reception",
            }
            duplicate = await client.post(
                handoff_url,
                json={"tool_call_id": "tool-transfer", "destination": "reception"},
                headers=voice_headers,
            )
            assert duplicate.json() == transfer.json()
            assert livekit.calls == [
                ("sip-call-example", f"handoff-{call_id}", "+421900000001")
            ]
            relinquished = await client.post(
                f"/internal/v1/calls/{call_id}/observations",
                json={
                    "observation_type": "agent_relinquished",
                    "conversation_status": "complete",
                },
                headers=voice_headers,
            )
            assert relinquished.status_code == 200
            assert relinquished.json()["status"] == "connected"
            handed_off_call = (await client.get(f"/admin/v1/calls/{call_id}")).json()
            assert handed_off_call["status"] == "connected"
            assert handed_off_call["handoff_destination"] == "reception"
            assert handed_off_call["handoff_participant_identity"] == (
                f"handoff-{call_id}"
            )
            assert handed_off_call["handoff_sip_call_id"] == "SCL_handoff_1"

            conflict = await client.post(
                claim_url,
                json={**payload, "room_name": "different-room"},
                headers=voice_headers,
            )
            assert conflict.status_code == 409

            fallback = {
                **payload,
                "sip_call_id": "SCL_fallback",
                "sip_call_id_full": None,
                "room_name": "sip-call-fallback",
                "participant_identity": "sip-caller-fallback",
            }
            first_fallback = await client.post(
                claim_url, json=fallback, headers=voice_headers
            )
            assert first_fallback.status_code == 200
            full_retry = await client.post(
                claim_url,
                json={**fallback, "sip_call_id_full": "telnyx-fallback@example.net"},
                headers=voice_headers,
            )
            assert full_retry.status_code == 200
            assert (
                full_retry.json()["call_session_id"]
                == first_fallback.json()["call_session_id"]
            )

            different = await client.post(
                claim_url,
                json={
                    **payload,
                    "sip_call_id": "SCL_inbound_2",
                    "sip_call_id_full": "telnyx-call-2@example.net",
                    "room_name": "sip-call-example-2",
                    "participant_identity": "sip-caller-example-2",
                },
                headers=voice_headers,
            )
            assert different.status_code == 200
            assert different.json()["call_session_id"] != call_id
            different_id = different.json()["call_session_id"]
            for observation in ("session_started", "participant_connected"):
                assert (
                    await client.post(
                        f"/internal/v1/calls/{different_id}/observations",
                        json={"observation_type": observation},
                        headers=voice_headers,
                    )
                ).status_code == 200
            livekit.fail = True
            failed_transfer = await client.post(
                f"/internal/v1/calls/{different_id}/handoff",
                json={"tool_call_id": "tool-failed", "destination": "reception"},
                headers=voice_headers,
            )
            assert failed_transfer.status_code == 502
            assert failed_transfer.json()["detail"]["code"] == "transfer_failed"

            unknown = await client.post(
                claim_url,
                json={
                    **payload,
                    "sip_call_id": "SCL_unknown",
                    "sip_call_id_full": "telnyx-unknown@example.net",
                    "called_number": "+421999999999",
                },
                headers=voice_headers,
            )
            assert unknown.status_code == 404
            invalid = await client.post(
                claim_url,
                json={
                    **payload,
                    "sip_call_id": "SCL_invalid",
                    "sip_call_id_full": "telnyx-invalid@example.net",
                    "called_number": "00421552301410",
                },
                headers=voice_headers,
            )
            assert invalid.status_code == 404

            async with database.transaction() as session:
                before = await session.scalar(
                    select(func.count()).select_from(CallSession)
                )
                await session.execute(
                    update(Tenant)
                    .where(Tenant.id == tenant_id)
                    .values(active_voice_runtime_revision_id=None)
                )
            unavailable = await client.post(
                claim_url,
                json={
                    **payload,
                    "sip_call_id": "SCL_no_runtime",
                    "sip_call_id_full": "telnyx-no-runtime@example.net",
                },
                headers=voice_headers,
            )
            assert unavailable.status_code == 409
            async with database.transaction() as session:
                assert await session.scalar(
                    select(func.count()).select_from(CallSession)
                ) == before
    finally:
        async with database.transaction() as session:
            tenant_ids = select(Tenant.id).where(Tenant.slug == "call-session-hotel")
            await session.execute(
                delete(Conversation).where(Conversation.tenant_id.in_(tenant_ids))
            )
            await session.execute(
                delete(CallSession).where(CallSession.tenant_id.in_(tenant_ids))
            )
            await session.execute(
                delete(Tenant).where(Tenant.slug == "call-session-hotel")
            )
            await session.execute(
                delete(SystemPrompt).where(SystemPrompt.key == "call_session_system")
            )
            await session.execute(
                delete(ProfilePrompt).where(ProfilePrompt.key == "call_session_hotel")
            )
        await database.close()
