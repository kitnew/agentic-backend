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
CONNECTION_ID = UUID("00000000-0000-0000-0000-000000000020")
NOW = datetime(2026, 8, 11, tzinfo=UTC)


def response(parsed: object, status: HTTPStatus = HTTPStatus.OK) -> Response[object]:
    return Response(
        status_code=status, content=b"", headers=httpx.Headers(), parsed=parsed
    )


def connection() -> IntegrationConnectionResponse:
    return IntegrationConnectionResponse.from_dict(
        {
            "config": {"allowed_hosts": ["example.test"]},
            "created_at": NOW.isoformat(),
            "credential_fingerprint": "a" * 64,
            "credential_version": 1,
            "id": str(CONNECTION_ID),
            "key": "recording_webhook",
            "provider": "managed_webhook",
            "revision": 1,
            "status": "active",
            "tenant_id": str(TENANT_ID),
            "updated_at": NOW.isoformat(),
        }
    )


def settings() -> Settings:
    return Settings("https://backend.example", "secret", Path("definitions"))


def mock_tenant(monkeypatch: pytest.MonkeyPatch, seen: list[str]) -> None:
    def resolve(slug: str, *, client: object) -> Response[object]:
        seen.append(slug)
        return response(
            TenantResponse.from_dict(
                {
                    "active_release_id": None,
                    "business_type": "hotel",
                    "created_at": NOW.isoformat(),
                    "display_name": "Penzión Grand",
                    "id": str(TENANT_ID),
                    "slug": slug,
                    "status": "active",
                    "updated_at": NOW.isoformat(),
                }
            )
        )

    monkeypatch.setattr(
        common.get_tenant_by_slug_admin_v1_tenants_by_slug_slug_get,
        "sync_detailed",
        resolve,
    )


def test_integration_list_and_show_resolve_tenant_slug(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []
    mock_tenant(monkeypatch, seen)
    monkeypatch.setattr(
        integrations.list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
        "sync_detailed",
        lambda tenant_id, *, client: response([connection()]),
    )

    integrations.run_integration(settings(), "list", "penzion-grand")
    assert "recording_webhook\tmanaged_webhook\tactive" in capsys.readouterr().out
    integrations.run_integration(
        settings(), "show", "penzion-grand", "recording_webhook"
    )
    assert "Credential version: 1" in capsys.readouterr().out
    assert seen == ["penzion-grand", "penzion-grand"]


def test_integration_create_and_delete_use_existing_admin_api(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_tenant(monkeypatch, [])
    created: list[dict[str, object]] = []
    deleted: list[tuple[UUID, UUID]] = []
    monkeypatch.setattr(
        integrations.create_connection_admin_v1_tenants_tenant_id_integration_connections_post,
        "sync_detailed",
        lambda tenant_id, *, client, body: (
            created.append(body.to_dict()) or response(connection(), HTTPStatus.CREATED)
        ),
    )
    monkeypatch.setattr(
        integrations.list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
        "sync_detailed",
        lambda tenant_id, *, client: response([connection()]),
    )
    monkeypatch.setattr(
        integrations.delete_connection_admin_v1_tenants_tenant_id_integration_connections_connection_id_delete,
        "sync_detailed",
        lambda tenant_id, connection_id, *, client: (
            deleted.append((tenant_id, connection_id))
            or response(None, HTTPStatus.NO_CONTENT)
        ),
    )

    integrations.run_integration(
        settings(),
        "create",
        "penzion-grand",
        "recording_webhook",
        provider="managed_webhook",
        config_json='{"allowed_hosts":["example.test"]}',
    )
    integrations.run_integration(
        settings(), "delete", "penzion-grand", "recording_webhook"
    )

    assert created == [
        {
            "config": {"allowed_hosts": ["example.test"]},
            "key": "recording_webhook",
            "provider": "managed_webhook",
        }
    ]
    assert deleted == [(TENANT_ID, CONNECTION_ID)]
    assert "Integration: recording_webhook" in capsys.readouterr().out


def test_integration_show_rejects_missing_or_ambiguous_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_tenant(monkeypatch, [])
    items: list[IntegrationConnectionResponse] = []
    monkeypatch.setattr(
        integrations.list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
        "sync_detailed",
        lambda tenant_id, *, client: response(items),
    )
    with pytest.raises(common.CommandError, match="unknown integration"):
        integrations.run_integration(
            settings(), "show", "penzion-grand", "recording_webhook"
        )

    items.extend((connection(), connection()))
    with pytest.raises(common.CommandError, match="ambiguous integration"):
        integrations.run_integration(
            settings(), "show", "penzion-grand", "recording_webhook"
        )
