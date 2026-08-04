import json
from datetime import datetime, timezone
from urllib.error import URLError

import pytest

from app.capabilities.providers.google_sheets import GoogleSheetsReservationProvider
from app.capabilities.registry import CapabilityRegistry
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityRequest
from app.tenants.loader import TenantConfigInvalidError, TenantConfigLoader

from tests.test_reservation_requests import Sheets, request


class Response:
    def __init__(self, body=None, status=200):
        self.body = json.dumps(body or {"output": {"request_id": "make-1"}}).encode()
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


def tenant_with_webhook(capability_name: str):
    tenant = TenantConfigLoader().load("penzion_grand")
    capabilities = dict(tenant.capabilities)
    capabilities[capability_name] = capabilities[capability_name].model_copy(
        update={
            "provider": "make_webhook",
            "config": {"webhook_url": "https://make.example.test/hook"},
        }
    )
    return tenant.model_copy(update={"capabilities": capabilities})


def router(tenant, sheets):
    registry = CapabilityRegistry()
    registry.providers["google_sheets"] = GoogleSheetsReservationProvider(sheets)
    return CapabilityRouter(
        registry,
        clock=lambda: datetime(2026, 7, 21, 12, tzinfo=timezone.utc),
    )


def execute(tenant, sheets, capability_request):
    return router(tenant, sheets).execute(tenant, capability_request)


@pytest.mark.parametrize(
    "name",
    [
        "reservation.create_request",
        "reservation.change_request",
        "reservation.cancel_request",
    ],
)
def test_each_reservation_action_can_select_webhook_without_internal_execution(
    monkeypatch, name
):
    calls = []

    def fake_urlopen(http_request, timeout):
        calls.append((json.loads(http_request.data), timeout))
        return Response()

    monkeypatch.setattr(
        "app.capabilities.providers.make_webhook.urlopen", fake_urlopen
    )
    sheets = Sheets()
    result = execute(tenant_with_webhook(name), sheets, request(name))

    assert result.status == "success"
    assert result.provider == "make_webhook"
    assert result.output == {"request_id": "make-1"}
    assert calls[0][0]["capability"] == name
    assert calls[0][1] == 15
    assert sheets.appends == []


def test_webhook_failure_does_not_fall_back_to_google_sheets(monkeypatch):
    monkeypatch.setattr(
        "app.capabilities.providers.make_webhook.urlopen",
        lambda *_args, **_kwargs: Response(status=500),
    )
    sheets = Sheets()

    result = execute(
        tenant_with_webhook("reservation.create_request"),
        sheets,
        request("reservation.create_request"),
    )

    assert result.status == "failed"
    assert result.error == "webhook_http_500"
    assert sheets.appends == []


def test_webhook_api_key_uses_configured_environment_header(monkeypatch):
    monkeypatch.setenv("MAKE_WEBHOOK_API_KEY", "test123")
    captured = {}

    def fake_urlopen(http_request, timeout):
        captured.update({key.lower(): value for key, value in http_request.header_items()})
        return Response()

    monkeypatch.setattr(
        "app.capabilities.providers.make_webhook.urlopen", fake_urlopen
    )
    tenant = tenant_with_webhook("reservation.create_request")
    capability = tenant.capabilities["reservation.create_request"].model_copy(
        update={
            "config": {
                "webhook_url": "https://make.example.test/hook",
                "webhook_api_key_env": "MAKE_WEBHOOK_API_KEY",
            }
        }
    )
    tenant = tenant.model_copy(
        update={
            "capabilities": {
                **tenant.capabilities,
                "reservation.create_request": capability,
            }
        }
    )

    result = execute(tenant, Sheets(), request("reservation.create_request"))

    assert result.status == "success"
    assert captured["x-make-apikey"] == "test123"


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (TimeoutError(), "webhook_timeout"),
        (URLError("offline"), "webhook_request_failed:URLError"),
    ],
)
def test_webhook_timeout_and_transport_failure_are_normalized_without_fallback(
    monkeypatch, failure, error
):
    def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("app.capabilities.providers.make_webhook.urlopen", fail)
    sheets = Sheets()

    result = execute(
        tenant_with_webhook("reservation.cancel_request"),
        sheets,
        request("reservation.cancel_request"),
    )

    assert result.status == "failed"
    assert result.error == error
    assert sheets.appends == []


def test_validation_and_availability_guard_run_before_webhook(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.capabilities.providers.make_webhook.urlopen",
        lambda *_args, **_kwargs: calls.append(True) or Response(),
    )

    invalid = execute(
        tenant_with_webhook("reservation.create_request"),
        Sheets(),
        request("reservation.create_request", confirmed=False),
    )
    assert invalid.error == "invalid_reservation_request"
    assert calls == []

    busy = Sheets(
        values=[
            ["header"] * 31,
            ["2026-08-29"] + ["busy"] * 30,
            ["2026-08-30"] + ["busy"] * 30,
        ]
    )
    unavailable = execute(
        tenant_with_webhook("reservation.change_request"),
        busy,
        request(
            "reservation.change_request",
            check_in="2026-08-29",
            check_out="2026-08-31",
            room_type="three_bed",
            room_count=1,
        )
    )

    assert unavailable.error == "requested_stay_not_available"
    assert calls == []
    assert busy.appends == []


def test_check_availability_remains_internal_when_actions_use_webhook(monkeypatch):
    def unexpected_webhook(*_args, **_kwargs):
        raise AssertionError("availability should remain internal")

    monkeypatch.setattr(
        "app.capabilities.providers.make_webhook.urlopen", unexpected_webhook
    )
    sheets = Sheets()
    result = execute(
        tenant_with_webhook("reservation.create_request"),
        sheets,
        CapabilityRequest(
            name="reservation.check_availability",
            input={
                "check_in": "2026-08-29",
                "check_out": "2026-08-31",
                "room_type": "two_bed",
                "room_count": 1,
            },
        )
    )

    assert result.status == "success"
    assert len(sheets.reads) == 1


def test_check_availability_can_be_explicitly_switched_to_webhook(monkeypatch):
    tenant = tenant_with_webhook("reservation.create_request")
    capabilities = dict(tenant.capabilities)
    capabilities["reservation.check_availability"] = capabilities[
        "reservation.check_availability"
    ].model_copy(
        update={
            "provider": "make_webhook",
            "config": {"webhook_url": "https://make.example.test/availability"},
        }
    )
    tenant = tenant.model_copy(update={"capabilities": capabilities})
    calls = []

    def fake_urlopen(http_request, timeout):
        calls.append(json.loads(http_request.data))
        return Response({"output": {"status": "available"}})

    monkeypatch.setattr(
        "app.capabilities.providers.make_webhook.urlopen", fake_urlopen
    )
    sheets = Sheets()
    result = execute(
        tenant,
        sheets,
        CapabilityRequest(
            name="reservation.check_availability",
            input={
                "check_in": "2026-08-29",
                "check_out": "2026-08-31",
                "room_type": "two_bed",
                "room_count": 1,
            },
        ),
    )

    assert result.status == "success"
    assert result.provider == "make_webhook"
    assert calls[0]["capability"] == "reservation.check_availability"
    assert sheets.reads == []


def test_tenant_config_validates_make_webhook_url(tmp_path):
    config = {
        "schema_version": 2,
        "tenant_id": "test",
        "name": "Test",
        "business_type": "hotel",
        "default_language": "en",
        "locale": "en-GB",
        "supported_locales": ["en-GB"],
        "timezone": "Europe/Bratislava",
        "agent": {"profile": "hotel_assistant"},
        "capabilities": {
            "reservation.create_request": {
                "enabled": True,
                "provider": "make_webhook",
                "config": {"webhook_url": "not-a-url"},
            }
        },
    }
    configs_dir = tmp_path / "configs"
    content_dir = tmp_path / "content"
    configs_dir.mkdir()
    content_dir.mkdir()
    (configs_dir / "test.yaml").write_text(json.dumps(config), encoding="utf-8")

    loader = TenantConfigLoader(configs_dir, content_dir)
    with pytest.raises(TenantConfigInvalidError, match="webhook_url"):
        loader.validate_all(CapabilityRegistry().provider_names())
