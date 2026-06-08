from pathlib import Path

from app.capabilities.registry import CapabilityRegistry
from app.tenants.loader import TenantConfigInvalidError, TenantConfigLoader


def test_tenant_config_validate_all_accepts_demo_restaurant():
    loaded = TenantConfigLoader().validate_all(CapabilityRegistry().provider_names())

    assert [tenant.tenant_id for tenant in loaded] == ["demo_restaurant"]


def test_tenant_config_rejects_unknown_provider(tmp_path: Path):
    config = tmp_path / "broken.yaml"
    config.write_text(
        """
tenant_id: broken
name: Broken
business_type: restaurant
default_language: en
timezone: Europe/Bratislava
agent_profile: restaurant_assistant
enabled_capabilities: {}
capabilities:
  reservation.create_request:
    enabled: true
    provider: missing_provider
policies:
  can_confirm_reservation: false
  requires_human_confirmation: true
""".strip(),
        encoding="utf-8",
    )

    try:
        TenantConfigLoader(tmp_path).validate_all(CapabilityRegistry().provider_names())
    except TenantConfigInvalidError as exc:
        assert "Unknown provider" in str(exc)
        return

    raise AssertionError("expected TenantConfigInvalidError")
