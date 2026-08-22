from contextlib import contextmanager
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from admin_client.generated.models.tenant_telephony_response import (
    TenantTelephonyResponse,
)
from admin_client.generated.types import Response
from control_plane.commands import telephony
from control_plane.settings import Settings

TENANT_ID = UUID("00000000-0000-4000-8000-000000000010")
SETTINGS = Settings("https://backend.example", "secret", Path("definitions"))


def response(parsed: object) -> Response[object]:
    return Response(
        status_code=HTTPStatus.OK,
        content=b"",
        headers=httpx.Headers(),
        parsed=parsed,
    )


def state(desired: dict[str, object]) -> TenantTelephonyResponse:
    return TenantTelephonyResponse.from_dict(
        {
            "tenant_id": str(TENANT_ID),
            "desired": desired,
            "draft_revision_id": "00000000-0000-4000-8000-000000000020",
            "draft_version": 3,
            "published_revision_id": None,
            "provisioning_status": "pending",
            "last_error": None,
            "last_reconciled_at": None,
            "readiness": {
                "phone_number": "pending",
                "incoming_calls": "pending",
                "outgoing_calls": "pending",
                "human_handoff": "pending",
            },
        }
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> object:
    value = object()

    @contextmanager
    def opened(settings: Settings):
        yield value

    monkeypatch.setattr(telephony, "_client", opened)
    monkeypatch.setattr(
        telephony, "_tenant", lambda selected, slug: SimpleNamespace(id=TENANT_ID)
    )
    return value


def test_show_and_status_use_the_aggregate_api(
    monkeypatch: pytest.MonkeyPatch, client: object, capsys: pytest.CaptureFixture[str]
) -> None:
    desired = {"phone_number": None, "handoff": {"destinations": {}}}
    shown: list[str] = []
    monkeypatch.setattr(
        telephony.show_tenant_telephony_admin_v1_tenants_tenant_id_telephony_get,
        "sync_detailed",
        lambda tenant_id, *, client: shown.append("show") or response(state(desired)),
    )
    monkeypatch.setattr(
        telephony.tenant_telephony_status_admin_v1_tenants_tenant_id_telephony_status_get,
        "sync_detailed",
        lambda tenant_id, *, client: shown.append("status") or response(state(desired)),
    )

    telephony.run_tenant_telephony(SETTINGS, "show", "hotel")
    telephony.run_tenant_telephony(SETTINGS, "status", "hotel")

    assert shown == ["show", "status"]
    assert capsys.readouterr().out.count('"provisioning_status": "pending"') == 2


def test_number_and_handoff_commands_preserve_one_desired_state(
    monkeypatch: pytest.MonkeyPatch, client: object
) -> None:
    desired: dict[str, object] = {
        "phone_number": None,
        "handoff": {"destinations": {}},
    }
    saved: list[dict[str, object]] = []

    def show(tenant_id: UUID, *, client: object) -> Response[object]:
        return response(state(desired))

    def save(
        tenant_id: UUID, *, client: object, body: object, if_match: str
    ) -> Response[object]:
        desired.clear()
        desired.update(body.to_dict())
        saved.append(dict(desired))
        return response(state(desired))

    monkeypatch.setattr(
        telephony.show_tenant_telephony_admin_v1_tenants_tenant_id_telephony_get,
        "sync_detailed",
        show,
    )
    monkeypatch.setattr(
        telephony.save_tenant_telephony_admin_v1_tenants_tenant_id_telephony_put,
        "sync_detailed",
        save,
    )

    telephony.run_tenant_telephony(
        SETTINGS, "set-number", "hotel", number="+421551234567"
    )
    telephony.run_tenant_telephony(
        SETTINGS,
        "handoff-set",
        "hotel",
        destination="reception",
        number="+421900000001",
        label="Reception",
    )
    telephony.run_tenant_telephony(
        SETTINGS, "handoff-remove", "hotel", destination="reception"
    )

    assert saved[0]["phone_number"] == "+421551234567"
    assert saved[1]["handoff"] == {
        "destinations": {
            "reception": {
                "description": "Reception",
                "phone_number": "+421900000001",
            }
        }
    }
    assert saved[2]["handoff"] == {"destinations": {}}
