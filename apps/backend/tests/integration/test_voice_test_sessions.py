from collections.abc import Callable
from uuid import UUID

import jwt
import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.calls.models import CallSession
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.calls.service import CallSessionService
from backend_core.modules.conversations.models import Conversation, ConversationMessage
from backend_core.modules.tenants.models import (
    KnowledgeBase,
    KnowledgeBaseRevision,
    ProfilePrompt,
    ProfilePromptRevision,
    PromptSet,
    PromptSetRevision,
    SystemPrompt,
    SystemPromptRevision,
    Tenant,
    TenantConfigRevision,
    TenantPrompt,
    TenantPromptRevision,
)
from backend_core.platform.database import Database
from backend_core.platform.livekit import LiveKitAdapter
from contracts import LiveKitJobMetadata
from httpx import ASGITransport, AsyncClient
from prompt_fixtures import publish_config, publish_prompt_set
from runtime_fixtures import apply_voice_runtime
from sqlalchemy import delete, select, update


async def cleanup_tenants(database: Database, *slugs: str) -> None:
    async with database.transaction() as session:
        tenant_ids = select(Tenant.id).where(Tenant.slug.in_(slugs))
        await session.execute(
            update(Tenant)
            .where(Tenant.slug.in_(slugs))
            .values(active_prompt_set_revision_id=None)
        )
        await session.execute(
            update(Tenant)
            .where(Tenant.slug.in_(slugs))
            .values(active_voice_runtime_revision_id=None)
        )
        await session.execute(
            update(Tenant)
            .where(Tenant.slug.in_(slugs))
            .values(active_config_revision_id=None)
        )
        await session.execute(
            delete(ConversationMessage).where(
                ConversationMessage.tenant_id.in_(tenant_ids)
            )
        )
        await session.execute(
            delete(Conversation).where(Conversation.tenant_id.in_(tenant_ids))
        )
        await session.execute(
            delete(CallSession).where(CallSession.tenant_id.in_(tenant_ids))
        )
        await session.execute(
            delete(PromptSetRevision).where(PromptSetRevision.tenant_id.in_(tenant_ids))
        )
        await session.execute(
            delete(TenantPromptRevision).where(
                TenantPromptRevision.tenant_id.in_(tenant_ids)
            )
        )
        await session.execute(
            delete(KnowledgeBaseRevision).where(
                KnowledgeBaseRevision.tenant_id.in_(tenant_ids)
            )
        )
        await session.execute(
            delete(PromptSet).where(PromptSet.tenant_id.in_(tenant_ids))
        )
        await session.execute(
            delete(TenantPrompt).where(TenantPrompt.tenant_id.in_(tenant_ids))
        )
        await session.execute(
            delete(KnowledgeBase).where(KnowledgeBase.tenant_id.in_(tenant_ids))
        )
        await session.execute(
            delete(TenantConfigRevision).where(
                TenantConfigRevision.tenant_id.in_(tenant_ids)
            )
        )
        await session.execute(delete(Tenant).where(Tenant.slug.in_(slugs)))
        for revision_model, parent_model, parent_field in (
            (SystemPromptRevision, SystemPrompt, "system_prompt_id"),
            (ProfilePromptRevision, ProfilePrompt, "profile_prompt_id"),
        ):
            parent_ids = select(parent_model.id).where(
                parent_model.key.in_(("default", "hotel_assistant"))
            )
            await session.execute(
                delete(revision_model).where(
                    getattr(revision_model, parent_field).in_(parent_ids)
                )
            )
            await session.execute(
                delete(parent_model).where(
                    parent_model.key.in_(("default", "hotel_assistant"))
                )
            )


class FakeLiveKit:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        fail_dispatch: bool = False,
        fail_token: bool = False,
    ) -> None:
        self.database = database
        self.fail_dispatch = fail_dispatch
        self.fail_token = fail_token
        self.created: list[dict[str, str]] = []
        self.deleted: list[tuple[str, str]] = []
        self.deleted_rooms: list[str] = []
        self.token_issuer = LiveKitAdapter(
            url=settings.livekit_url,
            api_key=settings.livekit_api_key.get_secret_value(),
            api_secret=settings.livekit_api_secret.get_secret_value(),
            participant_token_ttl_seconds=(
                settings.livekit_participant_token_ttl_seconds
            ),
        )

    async def start(self) -> None:
        return None

    async def create_dispatch(
        self,
        *,
        agent_name: str,
        room_name: str,
        metadata: str,
    ) -> str:
        if self.fail_dispatch:
            raise RuntimeError("dispatch rejected")
        parsed = LiveKitJobMetadata.model_validate_json(metadata)
        async with self.database.transaction() as session:
            assert await CallSessionRepository(session).get(parsed.call_session_id)
        self.created.append(
            {
                "agent_name": agent_name,
                "room_name": room_name,
                "metadata": metadata,
            }
        )
        return f"dispatch-{parsed.call_session_id}"

    async def delete_dispatch(self, dispatch_id: str, room_name: str) -> None:
        self.deleted.append((dispatch_id, room_name))

    async def delete_room(self, room_name: str) -> None:
        self.deleted_rooms.append(room_name)

    def issue_participant_token(self, *, room_name: str, identity: str) -> str:
        if self.fail_token:
            raise RuntimeError("token failed")
        return self.token_issuer.issue_participant_token(
            room_name=room_name,
            identity=identity,
        )

    async def aclose(self) -> None:
        await self.token_issuer.aclose()


async def create_voice_ready_tenant(client: AsyncClient, slug: str) -> str:
    tenant = await client.post(
        "/admin/v1/tenants",
        json={
            "slug": slug,
            "display_name": slug,
            "business_type": "hotel",
        },
    )
    assert tenant.status_code == 201
    tenant_id = tenant.json()["id"]
    await publish_prompt_set(client, tenant_id, system_text="Pinned system A")
    await publish_config(client, tenant_id, greeting="Pinned greeting A")
    await apply_voice_runtime(client, tenant_id)
    return tenant_id


@pytest.mark.asyncio
async def test_admin_web_call_dispatch_token_and_pinned_runtime_context(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
    service_token: Callable[..., str],
) -> None:
    database = Database(migrated_database_url)
    livekit = FakeLiveKit(database, app_settings)
    app = create_app(settings=app_settings, database=database, livekit=livekit)  # type: ignore[arg-type]
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            tenant_id = await create_voice_ready_tenant(client, "web-call-hotel")
            response = await client.post(
                "/admin/v1/voice/test-sessions",
                json={"tenant_id": tenant_id},
            )
            assert response.status_code == 201
            created = response.json()
            call_id = created["call_session_id"]
            assert created["room_name"] == f"call_{call_id}"
            assert created["livekit_url"] == app_settings.livekit_public_url
            assert created["participant_identity"].startswith("manual-test-")

            assert len(livekit.created) == 1
            dispatch = livekit.created[0]
            assert dispatch["agent_name"] == app_settings.livekit_agent_name
            assert dispatch["room_name"] == created["room_name"]
            assert LiveKitJobMetadata.model_validate_json(
                dispatch["metadata"]
            ).model_dump() == {"call_session_id": UUID(call_id)}

            token = jwt.decode(
                created["participant_token"],
                app_settings.livekit_api_secret.get_secret_value(),
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
            assert 0 < token["exp"] - token["nbf"] <= 600
            assert token["sub"] == created["participant_identity"]
            assert token["video"] == {
                "roomJoin": True,
                "room": created["room_name"],
                "canPublish": True,
                "canSubscribe": True,
                "canPublishData": False,
                "canPublishSources": ["microphone"],
            }

            lifecycle = await client.get(f"/admin/v1/voice/test-sessions/{call_id}")
            assert lifecycle.status_code == 200
            assert set(lifecycle.json()) == {
                "call_session_id",
                "status",
                "started_at",
                "connected_at",
                "ended_at",
                "failure_reason",
            }

            await publish_prompt_set(client, tenant_id, system_text="System B")
            await publish_config(client, tenant_id, greeting="Greeting B")

            runtime_token = service_token(
                service="voice-agent",
                scopes=["call-session:runtime-context:read"],
                secret=app_settings.voice_agent_service_secret.get_secret_value(),
            )
            runtime_headers = {"Authorization": f"Bearer {runtime_token}"}
            runtime = await client.get(
                f"/internal/v1/calls/{call_id}/runtime-context",
                headers=runtime_headers,
            )
            assert runtime.status_code == 200
            assert runtime.json()["greeting"] == "Pinned greeting A"
            assert runtime.json()["prompt"]["system_prompt"] == ("Pinned system A")
            assert runtime.json()["prompt"]["knowledge_context"] == (
                "Breakfast starts at seven."
            )
            assert runtime.json()["prompt"]["knowledge_base_revision_id"]
            assert runtime.json()["voice_runtime_revision_id"]
            assert runtime.json()["voice_runtime"]["locale"] == "sk-SK"
            assert runtime.json()["voice_runtime"]["tts"]["voice_id"] == "voice-a"
            runtime_text = runtime.text.lower()
            assert "api_key" not in runtime_text
            assert "azure_endpoint" not in runtime_text
            assert "azure_deployment" not in runtime_text
            assert (
                not {
                    "schema_version",
                    "prompt_bundle_revision_id",
                    "spreadsheet_id",
                    "request_mapping",
                    "credential_ref",
                }
                & runtime.json().keys()
            )
            async with database.transaction() as session:
                await session.execute(
                    update(CallSession)
                    .where(CallSession.id == UUID(call_id))
                    .values(voice_runtime_revision_id=None)
                )
            legacy_runtime = await client.get(
                f"/internal/v1/calls/{call_id}/runtime-context",
                headers=runtime_headers,
            )
            assert legacy_runtime.status_code == 409
            assert legacy_runtime.json()["detail"]["code"] == (
                "historical_call_voice_runtime_unavailable"
            )
            assert (
                await client.post(
                    f"/internal/v1/call-sessions/{call_id}/activate",
                    headers=runtime_headers,
                )
            ).status_code == 403
    finally:
        await cleanup_tenants(database, "web-call-hotel")
        await livekit.aclose()
        await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["dispatch", "persistence", "token"])
async def test_livekit_setup_failure_is_compensated_and_marks_call_failed(
    failure: str,
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(migrated_database_url)
    livekit = FakeLiveKit(
        database,
        app_settings,
        fail_dispatch=failure == "dispatch",
        fail_token=failure == "token",
    )
    app = create_app(settings=app_settings, database=database, livekit=livekit)  # type: ignore[arg-type]
    transport = ASGITransport(app=app)
    if failure == "persistence":

        async def fail_persistence(*args, **kwargs):
            raise RuntimeError("dispatch persistence failed")

        monkeypatch.setattr(CallSessionService, "set_dispatch", fail_persistence)

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            tenant_id = await create_voice_ready_tenant(
                client,
                f"{failure}-failure-hotel",
            )
            response = await client.post(
                "/admin/v1/voice/test-sessions",
                json={"tenant_id": tenant_id},
            )
            assert response.status_code == 502
            call_id = response.json()["detail"]["call_session_id"]
            lifecycle = await client.get(f"/admin/v1/voice/test-sessions/{call_id}")
            assert lifecycle.json()["status"] == "failed"
            assert lifecycle.json()["failure_reason"] == "livekit_setup_failed"
            assert bool(livekit.deleted) is (failure != "dispatch")
            assert bool(livekit.deleted_rooms) is (failure != "dispatch")
    finally:
        await cleanup_tenants(database, f"{failure}-failure-hotel")
        await livekit.aclose()
        await database.close()


@pytest.mark.asyncio
async def test_admin_test_session_idempotency_creates_one_conversation(
    migrated_database_url: str,
    app_settings: Settings,
    admin_headers: dict[str, str],
) -> None:
    database = Database(migrated_database_url)
    livekit = FakeLiveKit(database, app_settings)
    app = create_app(settings=app_settings, database=database, livekit=livekit)  # type: ignore[arg-type]
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            tenant_id = await create_voice_ready_tenant(
                client,
                "idempotent-test-session-hotel",
            )
            request_headers = {"Idempotency-Key": "test-session-1"}
            first = await client.post(
                "/admin/v1/voice/test-sessions",
                json={"tenant_id": tenant_id},
                headers=request_headers,
            )
            replay = await client.post(
                "/admin/v1/voice/test-sessions",
                json={"tenant_id": tenant_id},
                headers=request_headers,
            )
            assert first.status_code == 201
            assert replay.status_code == 200
            assert replay.json()["call_session_id"] == first.json()["call_session_id"]
            assert len(livekit.created) == 1

            conversation = await client.get(
                f"/admin/v1/calls/{first.json()['call_session_id']}/conversation"
            )
            assert conversation.status_code == 200
            assert conversation.json()["status"] == "open"
            assert conversation.json()["messages"] == []
    finally:
        await cleanup_tenants(database, "idempotent-test-session-hotel")
        await livekit.aclose()
        await database.close()
