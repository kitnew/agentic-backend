from collections.abc import Callable
from uuid import uuid4

import pytest
from backend_core.bootstrap import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.platform.database import Database
from httpx import ASGITransport, AsyncClient


def config_v2(prompt_revision_id: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "prompt_bundle_revision_id": prompt_revision_id,
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


async def prepare_voice_ready_tenant(client: AsyncClient) -> tuple[str, str, str]:
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

    prompt_drafts_url = (
        f"/admin/v1/tenants/{tenant_id}/prompt-bundle/drafts"
    )
    prompt_draft = await client.post(
        prompt_drafts_url,
        json={"system_instructions": "You are a hotel assistant."},
    )
    assert prompt_draft.status_code == 201
    prompt_revision_id = prompt_draft.json()["id"]
    assert (
        await client.post(
            f"{prompt_drafts_url}/{prompt_revision_id}/publish"
        )
    ).status_code == 200

    config_drafts_url = f"/admin/v1/tenants/{tenant_id}/config/drafts"
    config_draft = await client.post(
        config_drafts_url,
        json={"config": config_v2(prompt_revision_id)},
    )
    assert config_draft.status_code == 201
    config_revision_id = config_draft.json()["id"]
    assert (
        await client.post(
            f"{config_drafts_url}/{config_revision_id}/publish"
        )
    ).status_code == 200

    route = await client.post(
        f"/admin/v1/tenants/{tenant_id}/inbound-routes",
        json={"normalized_did": "+421552301410"},
    )
    assert route.status_code == 201
    return tenant_id, config_revision_id, prompt_revision_id


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
        scopes=["call-session:create", "call-session:write"],
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
            tenant_id, config_revision_id, prompt_revision_id = (
                await prepare_voice_ready_tenant(client)
            )
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
            assert created["prompt_bundle_revision_id"] == prompt_revision_id
            assert created["channel"] == "sip"
            assert created["direction"] == "inbound"
            assert created["status"] == "created"
            assert created["started_at"] is None
            assert created["ended_at"] is None
            assert created["failure_reason"] is None

            duplicate = await client.post(
                calls_url,
                json={**payload, "room_name": "another-room"},
                headers=voice_headers,
            )
            assert duplicate.status_code == 409

            activated = await client.post(
                f"{calls_url}/{call_id}/activate",
                headers=voice_headers,
            )
            assert activated.status_code == 200
            assert activated.json()["status"] == "active"
            assert activated.json()["started_at"] is not None
            assert (
                await client.post(
                    f"{calls_url}/{call_id}/activate",
                    headers=voice_headers,
                )
            ).json() == activated.json()

            completed = await client.post(
                f"{calls_url}/{call_id}/complete",
                headers=voice_headers,
            )
            assert completed.status_code == 200
            assert completed.json()["status"] == "completed"
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
                    json={**payload, "called_number": "+421552301499"},
                    headers=voice_headers,
                )
            ).status_code == 404
    finally:
        await database.close()
