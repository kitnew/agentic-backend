from collections.abc import Callable
from uuid import UUID

import jwt
import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.calls.service import CallSessionService
from backend_core.platform.database import Database
from backend_core.platform.livekit import LiveKitAdapter
from contracts import LiveKitJobMetadata
from httpx import ASGITransport, AsyncClient


def config_v2(prompt_id: str, greeting: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "prompt_bundle_revision_id": prompt_id,
        "localization": {
            "default_locale": "sk-SK",
            "timezone": "Europe/Bratislava",
        },
        "agent": {"display_name": "Amelia", "greeting": greeting},
        "conversation": {"scope": "property_only"},
        "capabilities": {},
    }


async def publish_prompt(
    client: AsyncClient,
    tenant_id: str,
    system_instructions: str,
) -> str:
    drafts_url = f"/admin/v1/tenants/{tenant_id}/prompt-bundle/drafts"
    draft = await client.post(
        drafts_url,
        json={
            "system_instructions": system_instructions,
            "tenant_instructions": "Be concise.",
            "knowledge_text": "Breakfast starts at seven.",
        },
    )
    assert draft.status_code == 201
    prompt_id = draft.json()["id"]
    assert (await client.post(f"{drafts_url}/{prompt_id}/publish")).status_code == 200
    return prompt_id


async def publish_config(
    client: AsyncClient,
    tenant_id: str,
    prompt_id: str,
    greeting: str,
) -> str:
    drafts_url = f"/admin/v1/tenants/{tenant_id}/config/drafts"
    draft = await client.post(
        drafts_url,
        json={"config": config_v2(prompt_id, greeting)},
    )
    assert draft.status_code == 201
    config_id = draft.json()["id"]
    assert (await client.post(f"{drafts_url}/{config_id}/publish")).status_code == 200
    return config_id


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
    prompt_id = await publish_prompt(client, tenant_id, "Pinned system A")
    await publish_config(client, tenant_id, prompt_id, "Pinned greeting A")
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
                "ended_at",
                "failure_reason",
            }

            prompt_b = await publish_prompt(client, tenant_id, "System B")
            await publish_config(client, tenant_id, prompt_b, "Greeting B")

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
            assert runtime.json()["prompt"]["system_instructions"] == (
                "Pinned system A"
            )
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
            assert (
                await client.post(
                    f"/internal/v1/call-sessions/{call_id}/activate",
                    headers=runtime_headers,
                )
            ).status_code == 403
    finally:
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
        await livekit.aclose()
        await database.close()
