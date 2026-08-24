from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from admin_client.generated.models.integration_connection_response import (
    IntegrationConnectionResponse,
)
from admin_client.generated.models.tenant_response import TenantResponse
from admin_client.generated.types import Response
from control_plane.commands import common, integrations
from control_plane.settings import Settings

TENANT_ID = UUID("00000000-0000-0000-0000-000000000010")
NOW = datetime(2026, 8, 11, tzinfo=UTC)


def response(parsed: object, status: HTTPStatus = HTTPStatus.OK) -> Response[object]:
    return Response(
        status_code=status, content=b"", headers=httpx.Headers(), parsed=parsed
    )


def connection(key: str = "previo") -> IntegrationConnectionResponse:
    return IntegrationConnectionResponse.from_dict(
        {
            "configuration": {
                "endpoint": "https://api.example.test/v1",
                "authentication": {"type": "none"},
                "headers": {"Accept": "application/json"},
            },
            "created_at": NOW.isoformat(),
            "enabled": False,
            "id": "00000000-0000-0000-0000-000000000020",
            "key": key,
            "kind": "http",
            "readiness": {
                "configuration": "valid",
                "credentials": "not_required",
                "ready": True,
                "usable": False,
                "issues": [],
            },
            "revision": 1,
            "tenant_id": str(TENANT_ID),
            "updated_at": NOW.isoformat(),
            "credential_status": None,
            "credential_version": None,
            "credential_fingerprint": None,
        }
    )


def settings() -> Settings:
    return Settings("https://backend.example", "secret", Path("definitions"))


def mock_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        common.get_tenant_by_slug_admin_v1_tenants_by_slug_slug_get,
        "sync_detailed",
        lambda slug, *, client: response(
            TenantResponse.from_dict(
                {
                    "active_release_id": None,
                    "business_type": "hotel",
                    "created_at": NOW.isoformat(),
                    "display_name": "Penzion Grand",
                    "id": str(TENANT_ID),
                    "slug": slug,
                    "status": "active",
                    "updated_at": NOW.isoformat(),
                }
            )
        ),
    )


def test_list_and_show_are_key_based_and_secret_free(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_tenant(monkeypatch)
    monkeypatch.setattr(
        integrations.list_connections_admin_v1_tenants_tenant_id_integrations_get,
        "sync_detailed",
        lambda tenant_id, *, client: response([connection()]),
    )
    integrations.run_integration(settings(), "list", "penzion-grand")
    assert "previo\thttp\tFalse\tTrue\tFalse" in capsys.readouterr().out
    integrations.run_integration(settings(), "show", "penzion-grand", "previo")
    output = capsys.readouterr().out
    assert "https://api.example.test/v1" in output
    assert "00000000-0000-0000-0000-000000000020" not in output


def test_create_is_minimal_and_does_not_configure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_tenant(monkeypatch)
    seen: list[dict[str, object]] = []
    monkeypatch.setattr(
        integrations.create_connection_admin_v1_tenants_tenant_id_integrations_post,
        "sync_detailed",
        lambda tenant_id, *, client, body: (
            seen.append(body.to_dict()) or response(connection(), HTTPStatus.CREATED)
        ),
    )
    integrations.run_integration(
        settings(), "create", "penzion-grand", "previo", kind="http"
    )
    assert seen == [{"key": "previo", "kind": "http"}]


def test_configure_uses_typed_candidate_and_etag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_tenant(monkeypatch)
    monkeypatch.setattr(
        integrations.list_connections_admin_v1_tenants_tenant_id_integrations_get,
        "sync_detailed",
        lambda tenant_id, *, client: response([connection()]),
    )
    seen: list[tuple[dict[str, object], str]] = []
    monkeypatch.setattr(
        integrations.configure_connection_admin_v1_tenants_tenant_id_integrations_key_put,
        "sync_detailed",
        lambda tenant_id, key, *, client, body, if_match: (
            seen.append((body.to_dict(), if_match)) or response(connection())
        ),
    )
    integrations.run_integration(
        settings(),
        "configure",
        "penzion-grand",
        "previo",
        endpoint="https://api.example.test",
        auth="none",
        headers=["Accept=application/json"],
    )
    assert seen[0][0]["configuration"]["endpoint"] == "https://api.example.test"
    assert seen[0][1] == '"1"'


def test_plan_delegates_and_hidden_credential_is_not_rendered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_tenant(monkeypatch)
    monkeypatch.setattr(
        integrations.list_connections_admin_v1_tenants_tenant_id_integrations_get,
        "sync_detailed",
        lambda tenant_id, *, client: response([connection()]),
    )
    from admin_client.generated.models.integration_plan import IntegrationPlan

    monkeypatch.setattr(
        integrations.plan_connection_admin_v1_tenants_tenant_id_integrations_key_plan_post,
        "sync_detailed",
        lambda tenant_id, key, *, client, body: response(
            IntegrationPlan.from_dict(
                {
                    "credential": "rotate",
                    "valid": True,
                    "would_be_ready": True,
                    "changes": [],
                    "issues": [],
                    "live_apply": True,
                }
            )
        ),
    )
    integrations.run_integration(
        settings(),
        "plan",
        "penzion-grand",
        "previo",
        endpoint="https://api.example.test",
        auth="api_key_header",
        api_key="secret-value",
    )
    output = capsys.readouterr().out
    assert "credential: rotate" in output
    assert "secret-value" not in output


def test_workspace_does_not_project_live_integration() -> None:
    from control_plane.workspace.model import LiveResourceKind, ResourceId
    from control_plane.workspace.registry import (
        ResourceCapability,
        resource_capabilities,
    )

    resource = ResourceId(
        "tenant", "penzion-grand", LiveResourceKind.INTEGRATION, "previo"
    )
    capabilities = resource_capabilities(resource)
    assert ResourceCapability.LIVE_MUTABLE in capabilities
    assert ResourceCapability.LOCAL_PROJECTABLE not in capabilities
    assert ResourceCapability.PUBLISHABLE not in capabilities
