import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient
from prompt_fixtures import create_voice_ready_tenant
from test_voice_test_sessions import cleanup_tenants


@pytest.mark.asyncio
async def test_conversation_append_is_ordered_idempotent_and_closes_with_call(
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
        scopes=[
            "call-session:create",
            "call-session:activate",
            "call-session:complete",
            "call-session:fail",
            "call-session:observe",
            "conversation-message:append",
        ],
        secret=app_settings.voice_agent_service_secret.get_secret_value(),
    )
    headers = {"Authorization": f"Bearer {token}"}
    tenant_slug = f"conversation-{uuid4().hex}"

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=admin_headers,
        ) as client:
            _tenant_id, called_number = await create_voice_ready_tenant(
                client, tenant_slug
            )
            call = await client.post(
                "/internal/v1/call-sessions",
                json={
                    "channel": "sip",
                    "called_number": called_number,
                    "provider": "livekit",
                    "provider_call_id": f"conversation-{uuid4().hex}",
                    "room_name": f"conversation-room-{uuid4().hex}",
                },
                headers=headers,
            )
            assert call.status_code == 201
            call_id = call.json()["id"]

            conversation = await client.get(f"/admin/v1/calls/{call_id}/conversation")
            assert conversation.status_code == 200
            assert conversation.headers["cache-control"] == "no-store"
            assert conversation.json()["status"] == "open"
            assert conversation.json()["messages"] == []

            source_created_at = datetime.now(UTC).isoformat()
            first = {
                "message_id": str(uuid4()),
                "role": "user",
                "content": "Máte voľnú izbu?",
                "interrupted": False,
                "source_created_at": source_created_at,
            }
            appended = await client.post(
                f"/internal/v1/calls/{call_id}/messages",
                json=first,
                headers=headers,
            )
            assert appended.status_code == 201
            assert appended.json()["sequence_number"] == 1

            replay = await client.post(
                f"/internal/v1/calls/{call_id}/messages",
                json=first,
                headers=headers,
            )
            assert replay.status_code == 200
            assert replay.json() == appended.json()

            conflict = await client.post(
                f"/internal/v1/calls/{call_id}/messages",
                json={**first, "content": "Другой текст"},
                headers=headers,
            )
            assert conflict.status_code == 409

            second = {
                **first,
                "message_id": str(uuid4()),
                "role": "assistant",
                "content": "Áno, máme voľnú izbu.",
                "interrupted": True,
            }
            concurrent = await asyncio.gather(
                *(
                    client.post(
                        f"/internal/v1/calls/{call_id}/messages",
                        json={**second, "message_id": str(uuid4())},
                        headers=headers,
                    )
                    for _ in range(2)
                )
            )
            assert sorted(
                response.json()["sequence_number"] for response in concurrent
            ) == [
                2,
                3,
            ]

            activated = await client.post(
                f"/internal/v1/call-sessions/{call_id}/activate",
                headers=headers,
            )
            assert activated.status_code == 200
            connected = await client.post(
                f"/internal/v1/calls/{call_id}/observations",
                json={"schema_version": 1, "observation_type": "participant_connected"},
                headers=headers,
            )
            assert connected.status_code == 200
            completed = await client.post(
                f"/internal/v1/call-sessions/{call_id}/complete",
                json={"conversation_status": "complete"},
                headers=headers,
            )
            assert completed.status_code == 200
            assert completed.json()["status"] == "ended"

            final = await client.get(f"/admin/v1/calls/{call_id}/conversation")
            assert [
                message["sequence_number"] for message in final.json()["messages"]
            ] == [1, 2, 3]
            assert final.json()["messages"][1]["interrupted"] is True
            assert final.json()["status"] == "complete"
            assert (
                await client.post(
                    f"/internal/v1/calls/{call_id}/messages",
                    json={**first, "message_id": str(uuid4())},
                    headers=headers,
                )
            ).status_code == 409
            assert (
                await client.post(
                    f"/internal/v1/call-sessions/{call_id}/complete",
                    json={"conversation_status": "complete"},
                    headers=headers,
                )
            ).status_code == 200
            assert (
                await client.post(
                    f"/internal/v1/call-sessions/{call_id}/complete",
                    json={"conversation_status": "incomplete"},
                    headers=headers,
                )
            ).status_code == 409
    finally:
        await cleanup_tenants(database, tenant_slug)
        await database.close()
