from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
import uvicorn
import yaml
from agentctl import main as agentctl
from backend_core.bootstrap.app import create_app
from backend_core.bootstrap.settings import Settings
from backend_core.modules.tenants.release_repository import TenantReleaseRepository
from backend_core.platform.database import Database
from backend_core.runtime.bundle_store import RuntimeBundleStore

ADMIN_TOKEN = "test-admin-token-with-at-least-32-characters"


def _policy() -> dict[str, Any]:
    return {
        "llm": {"provider": "azure_openai", "model": "gpt-4.1", "temperature": 0.2},
        "stt": {
            "provider": "elevenlabs",
            "model": "scribe",
            "server_vad": {
                "silence_threshold_seconds": 1,
                "activity_threshold": 0.5,
                "min_speech_ms": 100,
                "min_silence_ms": 200,
            },
        },
        "tts": {"provider": "elevenlabs", "model": "turbo", "voice_id": "voice"},
        "local_vad": {
            "min_speech_seconds": 0.2,
            "min_silence_seconds": 0.4,
            "activation_threshold": 0.5,
        },
        "turn": {
            "detection": "stt",
            "min_endpointing_delay_seconds": 0.2,
            "max_endpointing_delay_seconds": 1,
        },
    }


def _api(client: httpx.Client, method: str, path: str, **kwargs: Any) -> httpx.Response:
    response = client.request(method, path, **kwargs)
    assert response.is_success, response.text
    return response


def _seed_platform(client: httpx.Client) -> None:
    state = _api(client, "GET", "/admin/v1/platform/components/state").json()
    runtime_draft = state["runtime_draft"]
    system_prompt_draft = state["system_prompt_draft"]
    runtime = _api(
        client,
        "PUT",
        "/admin/v1/platform/components/runtime/draft",
        headers=(
            {}
            if runtime_draft is None
            else {"If-Match": f'"{runtime_draft["version"]}"'}
        ),
        json={"policy": _policy()},
    )
    system = _api(
        client,
        "PUT",
        "/admin/v1/platform/components/system-prompt/draft",
        headers=(
            {}
            if system_prompt_draft is None
            else {"If-Match": f'"{system_prompt_draft["version"]}"'}
        ),
        json={"text": "You are a helpful hotel assistant."},
    )
    _api(
        client,
        "PUT",
        "/admin/v1/platform/components/profiles/default/draft",
        json={"text": "Hotel profile."},
    )
    platform_state = _api(client, "GET", "/admin/v1/platform/components/state").json()
    profile_versions = {
        name: draft["version"]
        for name, draft in platform_state["profile_prompt_drafts"].items()
    }
    _api(
        client,
        "POST",
        "/admin/v1/platform/components/publish",
        json={
            "runtime_version": runtime.json()["version"],
            "system_prompt_version": system.json()["version"],
            "profile_prompt_versions": profile_versions,
        },
    )


@pytest_asyncio.fixture
async def backend_url(app_settings: Settings) -> Any:
    settings = app_settings.model_copy(
        update={
            "otel_enabled": False,
            "call_runtime_reconciliation_enabled": False,
            "telephony_reconciliation_enabled": False,
        }
    )
    app = create_app(settings)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()


def _run(
    url: str, workspace: Path, monkeypatch: pytest.MonkeyPatch, *args: str
) -> int:
    monkeypatch.setenv("AGENTCTL_TOKEN", ADMIN_TOKEN)
    return agentctl.main(["--api-url", url, "--state-dir", str(workspace), *args])


def _write_workspace(workspace: Path, slug: str) -> None:
    tenant = workspace / "tenants" / slug
    (tenant / "knowledge").mkdir(parents=True, exist_ok=True)
    (tenant / "tenant.yaml").write_text(
        yaml.safe_dump(
            {
                "business": {"name": "E2E Hotel", "type": "hotel"},
                "contact": {
                    "address": None,
                    "phones": ["+40123456789"],
                    "emails": [],
                    "website": None,
                },
                "localization": {"default_locale": "en-US", "timezone": "UTC"},
                "agent": {
                    "display_name": "E2E Concierge",
                    "greeting": "Welcome to E2E Hotel.",
                    "profile": "default",
                },
                "conversation": {"scope": "property_only"},
                "handoff": {
                    "destinations": {
                        "front_desk": {
                            "description": "Front desk",
                            "phone_number": "+40123456789",
                        }
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (tenant / "runtime.yaml").write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "model": "gpt-4.1",
                    "temperature": 0.2,
                    "reasoning_effort": None,
                },
                "stt": {"keyterms": ["Penzión Grand", "Kováčska"]},
                "tts": None,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (tenant / "tenant_prompt.md").write_text(
        "Always confirm reservation details before submitting.", encoding="utf-8"
    )
    (tenant / "knowledge" / "knowledge.md").write_text(
        "Check-in is at 15:00 and check-out is at 11:00.", encoding="utf-8"
    )
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "check_in": {"type": "string"},
            "check_out": {"type": "string"},
            "room_type": {"type": "integer"},
            "room_count": {"type": "integer"},
            "reservation_number": {"type": "string"},
        },
        "required": ["check_in", "check_out", "room_type", "room_count"],
    }
    operation = {
        "type": "http",
        "connection": "reservation-api",
        "method": "POST",
        "path": "/reservations/check",
        "query": None,
        "headers": {},
        "request": {
            "codec": "json",
            "content_type": None,
            "mapping": {
                "check_in": {"$expr": "business.stay.check_in"},
                "reservation_number": {"$expr": "business.custom.reservation_number"},
            },
        },
        "response": {
            "codec": "json",
            "mapping": {"status": {"$expr": "response.body.status"}},
        },
        "success_statuses": None,
        "timeout_seconds": 10.0,
    }
    (tenant / "capabilities.yaml").write_text(
        yaml.safe_dump(
            {
                "capabilities": {
                    "reservation.check_reservation": {
                        "enabled": True,
                        "description": "Check room availability.",
                        "announcement": "I will check availability.",
                        "agent_input_schema": schema,
                        "bindings": {
                            "check_in": "stay.check_in",
                            "check_out": "stay.check_out",
                            "room_type": "allocation.room_type",
                            "room_count": "allocation.room_count",
                            "reservation_number": "custom.reservation_number",
                        },
                        "business_policy": {
                            "requires_final_confirmation": False,
                            "requires_availability_proof": False,
                            "requires_caller_phone": False,
                            "availability_proof_ttl_seconds": None,
                        },
                        "execution": operation,
                        "result_schema": None,
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (tenant / "post_call.yaml").write_text(
        yaml.safe_dump(
            {
                "actions": [
                    {
                        "action_id": "send_transcript",
                        "inputs": {
                            "transcript": {"artifact": "transcript", "representation": "plain_text"}
                        },
                        "execution": {
                            **operation,
                            "request": {
                                "codec": "json",
                                "content_type": None,
                                "mapping": {
                                    "transcript": {"$expr": "inputs.transcript"}
                                },
                            },
                            "response": {"codec": "none", "mapping": None},
                        },
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_component_draft_save_materializes_updated_at_and_preserves_cas(
    backend_url: str,
) -> None:
    with httpx.Client(
        base_url=backend_url,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=10,
    ) as client:
        tenant = _api(
            client,
            "POST",
            "/admin/v1/tenants",
            json={
                "slug": f"draft-save-{uuid4().hex[:8]}",
                "display_name": "Draft Save Hotel",
                "business_type": "hotel",
                "status": "active",
            },
        ).json()
        tenant_id = tenant["id"]
        state = _api(
            client, "GET", f"/admin/v1/tenants/{tenant_id}/components/telephony"
        ).json()
        saved = _api(
            client,
            "PUT",
            f"/admin/v1/tenants/{tenant_id}/components/telephony/draft",
            headers={"If-Match": f'"{state["draft"]["version"]}"'},
            json={"payload": {"phone_number": "+40123456789"}},
        )
        assert saved.status_code == 200
        assert saved.json()["updated_at"]
        assert saved.json()["payload"]["phone_number"] == "+40123456789"
        stale = client.put(
            f"/admin/v1/tenants/{tenant_id}/components/telephony/draft",
            headers={"If-Match": f'"{state["draft"]["version"]}"'},
            json={"payload": {"phone_number": "+40123456780"}},
        )
        assert stale.status_code == 412


@pytest.mark.asyncio
async def test_control_plane_golden_path(
    backend_url: str,
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "definitions"
    with httpx.Client(
        base_url=backend_url,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=10,
    ) as client:
        fresh_platform = _api(client, "GET", "/admin/v1/platform/components/state").json()
        assert fresh_platform["runtime_draft"] is not None
        assert fresh_platform["system_prompt_draft"] is not None
        scoped_workspace = tmp_path / "platform-definitions"
        assert _run(backend_url, scoped_workspace, monkeypatch, "pull", "platform") == 0
        assert (scoped_workspace / "platform" / "runtime.yaml").exists()
        assert (scoped_workspace / "platform" / "system_prompt.md").exists()
        assert (scoped_workspace / "platform" / "profiles").is_dir()
        local_profile = scoped_workspace / "platform" / "profiles" / "hotel_assistant.md"
        local_profile.write_text("Hotel assistant", encoding="utf-8")
        assert _run(backend_url, scoped_workspace, monkeypatch, "status", "platform") == 0
        assert _run(backend_url, scoped_workspace, monkeypatch, "plan", "platform") == 0
        assert _run(backend_url, scoped_workspace, monkeypatch, "push", "platform") == 0
        assert _run(backend_url, scoped_workspace, monkeypatch, "pull", "platform") == 0
        assert _run(backend_url, scoped_workspace, monkeypatch, "status", "platform") == 0
        _seed_platform(client)
        slug = f"e2e-hotel-{uuid4().hex[:8]}"
        assert _run(backend_url, workspace, monkeypatch, "tenant", "create", slug, "--display-name", "E2E Hotel", "--business-type", "hotel") == 0
        tenant = _api(client, "GET", f"/admin/v1/tenants/by-slug/{slug}").json()
        tenant_id = tenant["id"]
        assert _run(backend_url, workspace, monkeypatch, "pull") == 0
        assert (workspace / "platform" / "runtime.yaml").exists()
        assert (workspace / "platform" / "system_prompt.md").exists()
        assert (workspace / "platform" / "profiles").is_dir()
        tenant_path = workspace / "tenants" / slug
        assert {item.name for item in tenant_path.iterdir()} == {
            "tenant.yaml", "runtime.yaml", "tenant_prompt.md", "capabilities.yaml", "post_call.yaml", "knowledge"
        }
        assert {item.name for item in (tenant_path / "knowledge").iterdir()} == {"knowledge.md"}
        assert "DTO" not in (tenant_path / "tenant_prompt.md").read_text()

        # The projection is operator-facing: connection keys only, no UUID or plan metadata.
        _write_workspace(workspace, slug)
        assert _run(backend_url, workspace, monkeypatch, "status", "tenant", slug) == 0

        assert _run(backend_url, workspace, monkeypatch, "integration", "create", slug, "reservation-api", "--kind", "http") == 0
        assert _run(backend_url, workspace, monkeypatch, "integration", "configure", slug, "reservation-api", "--endpoint", "https://example.com/v1", "--auth", "none") == 0
        assert _run(backend_url, workspace, monkeypatch, "integration", "validate", slug, "reservation-api") == 0
        assert _run(backend_url, workspace, monkeypatch, "integration", "enable", slug, "reservation-api") == 0
        integration = _api(client, "GET", f"/admin/v1/tenants/{tenant_id}/integrations/reservation-api").json()
        assert integration["key"] == "reservation-api"
        assert integration["kind"] == "http"
        assert integration["enabled"] is True
        assert integration["readiness"]["usable"] is True
        assert _run(backend_url, workspace, monkeypatch, "plan", "tenant", slug) == 0

        assert _run(backend_url, workspace, monkeypatch, "push", "tenant", slug) == 0
        capability_draft = _api(client, "GET", f"/admin/v1/tenants/{tenant_id}/components/capabilities").json()["draft"]["payload"]
        post_call_draft = _api(client, "GET", f"/admin/v1/tenants/{tenant_id}/components/post_call").json()["draft"]["payload"]
        connection_id = UUID(integration["id"])
        assert UUID(capability_draft["capabilities"]["reservation.check_reservation"]["execution"]["connection_id"]) == connection_id
        assert UUID(post_call_draft["actions"][0]["execution"]["connection_id"]) == connection_id
        assert "reservation-api" in (tenant_path / "capabilities.yaml").read_text()
        assert "connection_id" not in (tenant_path / "capabilities.yaml").read_text()
        assert tenant["active_release_id"] is None

        before_did = _api(client, "GET", f"/admin/v1/tenants/{tenant_id}/telephony/status").json()
        assert _run(backend_url, workspace, monkeypatch, "did", "assign", slug, "+40123456780") == 0
        after_did = _api(client, "GET", f"/admin/v1/tenants/{tenant_id}/telephony/status").json()
        assert after_did["draft"]["phone_number"] == "+40123456780"
        assert after_did["published"] is None
        assert before_did["published"] is None
        assert _run(backend_url, workspace, monkeypatch, "publish", "tenant", slug) == 0

        tenant = _api(client, "GET", f"/admin/v1/tenants/by-slug/{slug}").json()
        assert tenant["active_release_id"]
        database = Database(migrated_database_url)
        try:
            async with database.transaction() as session:
                release = await TenantReleaseRepository(session).active_release(UUID(tenant_id))
                assert release is not None
                assert all(
                    getattr(release, name) is not None
                    for name in (
                        "runtime_revision_id", "agent_revision_id", "prompt_revision_id",
                        "knowledge_revision_id", "capabilities_revision_id", "post_call_revision_id",
                        "telephony_revision_id", "runtime_bundle_id",
                    )
                )
                bundle = await RuntimeBundleStore(session).get(
                    UUID(tenant_id), release.id, release.runtime_bundle_id
                )
                assert bundle is not None
                assert bundle.payload["voice_runtime"]["stt"]["keyterms"] == [
                    "Kováčska",
                    "Penzión Grand",
                ]
                assert bundle.payload["capability_bindings"]
                assert bundle.payload["post_call_actions"]
                assert str(connection_id) in str(bundle.payload)
        finally:
            await database.close()
        status = _api(client, "GET", f"/admin/v1/tenants/{tenant_id}/telephony/status").json()
        assert status["draft"]["phone_number"] == status["published"]["phone_number"]
        assert status["provisioning"]["state"] == "pending"


@pytest.mark.asyncio
async def test_control_plane_conflict_and_did_do_not_publish(
    backend_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "definitions"
    with httpx.Client(
        base_url=backend_url,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=10,
    ) as client:
        _seed_platform(client)
        slug = f"conflict-hotel-{uuid4().hex[:8]}"
        assert _run(backend_url, workspace, monkeypatch, "tenant", "create", slug, "--display-name", "Conflict Hotel", "--business-type", "hotel") == 0
        assert _run(backend_url, workspace, monkeypatch, "pull", "tenant", slug) == 0
        prompt = workspace / "tenants" / slug / "tenant_prompt.md"
        prompt.write_text("local change", encoding="utf-8")
        state = _api(client, "GET", f"/admin/v1/tenants/by-slug/{slug}").json()
        tenant_id = state["id"]
        remote = _api(client, "GET", f"/admin/v1/tenants/{tenant_id}/authoring/prompt").json()
        _api(
            client,
            "PUT",
            f"/admin/v1/tenants/{tenant_id}/authoring/prompt",
            headers={"If-Match": remote["etag"]},
            json={"text": "remote change"},
        )
        assert _run(backend_url, workspace, monkeypatch, "push", "tenant", slug) == 2
        assert _api(client, "GET", f"/admin/v1/tenants/{tenant_id}/authoring/prompt").json()["value"]["text"] == "remote change"

        did_slug = f"did-hotel-{uuid4().hex[:8]}"
        assert _run(backend_url, workspace, monkeypatch, "tenant", "create", did_slug, "--display-name", "DID Hotel", "--business-type", "hotel") == 0
        did_tenant = _api(client, "GET", f"/admin/v1/tenants/by-slug/{did_slug}").json()
        assert _run(backend_url, workspace, monkeypatch, "did", "assign", did_slug, "+40123456781") == 0
        current = _api(client, "GET", f"/admin/v1/tenants/by-slug/{did_slug}").json()
        assert current["active_release_id"] is None
        did_status = _api(client, "GET", f"/admin/v1/tenants/{did_tenant['id']}/telephony/status").json()
        assert did_status["draft"]["phone_number"] == "+40123456781"
        assert did_status["published"] is None
