from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from admin_client.generated.models.authoring_plan import AuthoringPlan
from admin_client.generated.models.component_state_response import (
    ComponentStateResponse,
)
from admin_client.generated.models.tenant_response import TenantResponse
from admin_client.generated.models.tenant_telephony_status import TenantTelephonyStatus
from admin_client.generated.types import Response
from control_plane.commands import common, did
from control_plane.settings import Settings

TENANT_ID = UUID("00000000-0000-0000-0000-000000000010")
NOW = datetime(2026, 8, 23, tzinfo=UTC).isoformat()


def response(parsed: object, status: HTTPStatus = HTTPStatus.OK) -> Response[object]:
    return Response(
        status_code=status, content=b"", headers=httpx.Headers(), parsed=parsed
    )


def settings() -> Settings:
    return Settings("https://backend.example", "secret", Path("definitions"))


def state() -> ComponentStateResponse:
    return ComponentStateResponse.from_dict(
        {
            "component": "telephony",
            "draft": {
                "comment": None,
                "component": "telephony",
                "id": "00000000-0000-0000-0000-000000000021",
                "payload": {"phone_number": "+421900000002", "region": "eu"},
                "updated_at": NOW,
                "version": 4,
            },
            "active_revision": {
                "comment": None,
                "id": "00000000-0000-0000-0000-000000000022",
                "payload": {"phone_number": "+421900000001", "region": "eu"},
                "revision_number": 1,
                "sealed_at": NOW,
            },
        }
    )


def mock_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        common.get_tenant_by_slug_admin_v1_tenants_by_slug_slug_get,
        "sync_detailed",
        lambda slug, *, client: response(
            TenantResponse.from_dict(
                {
                    "active_release_id": None,
                    "business_type": "hotel",
                    "created_at": NOW,
                    "display_name": "Hotel",
                    "id": str(TENANT_ID),
                    "slug": slug,
                    "status": "active",
                    "updated_at": NOW,
                }
            )
        ),
    )


def test_assign_plans_saves_only_telephony_with_cas(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_tenant(monkeypatch)
    monkeypatch.setattr(
        did.component_state_admin_v1_tenants_tenant_id_components_component_get,
        "sync_detailed",
        lambda tenant_id, component, *, client: response(state()),
    )
    planned: list[dict[str, object]] = []
    saved: list[tuple[dict[str, object], str]] = []
    monkeypatch.setattr(
        did.plan_telephony_admin_v1_tenants_tenant_id_authoring_telephony_plan_post,
        "sync_detailed",
        lambda tenant_id, *, client, body: (
            planned.append(body.to_dict())
            or response(
                AuthoringPlan.from_dict(
                    {"valid": True, "changes": [], "errors": [], "warnings": []}
                )
            )
        ),
    )
    monkeypatch.setattr(
        did.save_draft_admin_v1_tenants_tenant_id_components_component_draft_put,
        "sync_detailed",
        lambda tenant_id, component, *, client, body, if_match: (
            saved.append((body.to_dict(), if_match))
            or response(type("Saved", (), {"version": 5})())
        ),
    )
    did.run_did(settings(), "assign", "debug-hotel", "+421900000003")
    assert planned == [{"phone_number": "+421900000003"}]
    assert saved == [
        ({"payload": {"phone_number": "+421900000003", "region": "eu"}}, '"4"')
    ]
    assert "publish" in capsys.readouterr().out.lower()


def test_remove_preserves_unrelated_fields_and_never_publishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_tenant(monkeypatch)
    monkeypatch.setattr(did, "_state", lambda client, tenant_id: state())
    monkeypatch.setattr(
        did,
        "_plan",
        lambda client, tenant_id, candidate: AuthoringPlan.from_dict({"valid": True}),
    )
    seen: list[dict[str, object]] = []
    monkeypatch.setattr(
        did.save_draft_admin_v1_tenants_tenant_id_components_component_draft_put,
        "sync_detailed",
        lambda tenant_id, component, *, client, body, if_match: (
            seen.append(body.to_dict()) or response(type("Saved", (), {"version": 5})())
        ),
    )
    did.run_did(settings(), "remove", "debug-hotel")
    assert seen == [{"payload": {"phone_number": None, "region": "eu"}}]


def test_show_distinguishes_draft_and_published_did(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_tenant(monkeypatch)
    monkeypatch.setattr(
        did.tenant_telephony_status_admin_v1_tenants_tenant_id_telephony_status_get,
        "sync_detailed",
        lambda tenant_id, *, client: response(
            TenantTelephonyStatus.from_dict(
                {
                    "tenant_id": str(TENANT_ID),
                    "draft": {"phone_number": "+421900000002"},
                    "published": {"phone_number": "+421900000001"},
                    "publication": "unpublished",
                    "claim": {"state": "active", "phone_number": "+421900000001"},
                    "provisioning": {"state": "ready", "last_error": None},
                }
            )
        ),
    )
    did.run_did(settings(), "show", "debug-hotel")
    output = capsys.readouterr().out
    assert "Draft DID: +421900000002" in output
    assert "Published DID: +421900000001" in output
    assert "Publication: unpublished" in output
    assert "Claim: active — +421900000001" in output
    assert "Provisioning: ready" in output
    assert "LiveKit" not in output


def test_telephony_resource_is_not_local_or_live() -> None:
    from control_plane.workspace.model import (
        DraftResourceKind,
        ResourceId,
        resource_path,
    )
    from control_plane.workspace.registry import (
        ResourceCapability,
        descriptors,
        resource_capabilities,
    )

    capabilities = resource_capabilities(
        ResourceId("tenant", "debug-hotel", DraftResourceKind.TELEPHONY)
    )
    assert ResourceCapability.REMOTE_READABLE in capabilities
    assert ResourceCapability.DRAFT_WRITABLE in capabilities
    assert ResourceCapability.PUBLISHABLE_PARTICIPANT in capabilities
    assert ResourceCapability.LOCAL_PROJECTABLE not in capabilities
    assert ResourceCapability.LIVE_MUTABLE not in capabilities
    assert all(item.kind is not DraftResourceKind.TELEPHONY for item in descriptors())
    with pytest.raises(ValueError, match="no local projection"):
        resource_path(
            Path("definitions"),
            ResourceId("tenant", "debug-hotel", DraftResourceKind.TELEPHONY),
        )
