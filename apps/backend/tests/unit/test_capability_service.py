import json
from pathlib import Path

import pytest
from backend_core.runtime.capabilities.domain import CapabilityValidationError
from backend_core.runtime.capabilities.service import CapabilityInvocationService
from contracts import TenantConfigV2, TenantConfigV3

V2_FIXTURE = (
    Path(__file__).parents[4]
    / "packages/contracts/tests/fixtures/tenant_config_v2.json"
)


def _config_v3() -> dict[str, object]:
    return {
        "schema_version": 3,
        "business": {"name": "Fixture Hotel", "type": "hotel"},
        "localization": {"default_locale": "sk-SK", "timezone": "Europe/Bratislava"},
        "agent": {
            "display_name": "Amelia",
            "greeting": "Dobry den",
            "profile": "hotel_assistant",
        },
        "conversation": {"scope": "property_only"},
    }


def test_capability_config_accepts_profile_schema_versions_only() -> None:
    assert isinstance(
        CapabilityInvocationService._capability_config(
            2, json.loads(V2_FIXTURE.read_text())
        ),
        TenantConfigV2,
    )
    assert isinstance(
        CapabilityInvocationService._capability_config(3, _config_v3()),
        TenantConfigV3,
    )
    with pytest.raises(CapabilityValidationError):
        CapabilityInvocationService._capability_config(1, {"schema_version": 1})
