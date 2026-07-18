from pathlib import Path

from app.capabilities.registry import CapabilityRegistry
from app.tenants.loader import TenantConfigInvalidError, TenantConfigLoader


def test_tenant_config_validate_all_accepts_demo_restaurant():
    loaded = TenantConfigLoader().validate_all(CapabilityRegistry().provider_names())

    assert [tenant.tenant_id for tenant in loaded] == ["demo_restaurant"]
    assert loaded[0].voice.stt.provider == "elevenlabs"


def test_tenant_config_defaults_voice_disabled_when_omitted(tmp_path: Path):
    config = tmp_path / "no_voice.yaml"
    config.write_text(
        """
tenant_id: no_voice
name: No Voice
business_type: restaurant
default_language: en
locale: en-US
timezone: Europe/Bratislava
agent:
  profile: restaurant_assistant
capabilities: {}
""".strip(),
        encoding="utf-8",
    )

    loaded = TenantConfigLoader(tmp_path).validate_all(CapabilityRegistry().provider_names())

    assert loaded[0].voice.enabled is False


def test_tenant_config_rejects_unknown_provider(tmp_path: Path):
    config = tmp_path / "broken.yaml"
    config.write_text(
        """
tenant_id: broken
name: Broken
business_type: restaurant
default_language: en
locale: en-US
timezone: Europe/Bratislava
agent:
  profile: restaurant_assistant
prompt:
  tenant_instructions: "Test"
business_info:
  opening_hours_text: "10:00 - 21:00"
reservation:
  mode: request_only
  requires_human_confirmation: true
  can_confirm_reservation: false
  required_fields:
    guest_name:
      required: true
      label: "name"
  schedule:
    weekly: {}
capabilities:
  reservation.create_request:
    enabled: true
    provider: missing_provider
""".strip(),
        encoding="utf-8",
    )

    try:
        TenantConfigLoader(tmp_path).validate_all(CapabilityRegistry().provider_names())
    except TenantConfigInvalidError as exc:
        assert "Unknown provider" in str(exc)
        return

    raise AssertionError("expected TenantConfigInvalidError")
