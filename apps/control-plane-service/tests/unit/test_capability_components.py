from uuid import uuid4

import pytest
from control_plane.domain.capabilities import (
    IntegrationConnectionRef,
    TenantCapabilitiesConfig,
    derive_tool_name,
    normalize_canonical_input,
    register_capability_components,
)
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    PlatformScope,
    TenantScope,
)
from control_plane.domain.components.errors import (
    InvalidComponentValue,
    ScopeNotAllowed,
)
from pydantic import ValidationError


def profile(**changes: object) -> dict[str, object]:
    return {
        "enabled": True,
        "description": "Create a reservation",
        "announcement": "Creating it now.",
        "agent_input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "phone": {"type": "string"},
                "check_in": {"type": "string", "format": "date"},
                "check_out": {"type": "string", "format": "date"},
                "custom_note": {"type": "string"},
            },
            "required": ["phone", "check_in", "check_out"],
        },
        "bindings": {
            "phone": "guest.phone",
            "check_in": "stay.check_in",
            "check_out": "stay.check_out",
        },
        "input_constraints": [
            {"kind": "date_range", "start": "stay.check_in", "end": "stay.check_out"}
        ],
        "execution": {
            "integration_connection_ref": str(uuid4()),
            "method": "POST",
            "path": "/reservations",
            "query": {"source": {"$expr": "request.source"}},
            "headers": {"X-Trace": "trace"},
            "request": {
                "codec": "json",
                "mapping": {"guest": {"$expr": "request.phone"}},
            },
            "response": {"codec": "json", "mapping": {"id": {"$expr": "response.id"}}},
            "timeout_seconds": 10,
        },
    } | changes


def test_tenant_capabilities_preserve_http_mapping_and_typed_ref() -> None:
    value = TenantCapabilitiesConfig.model_validate(
        {"capabilities": {"reservation.create": profile()}}
    )
    execution = value.capabilities["reservation.create"].execution  # type: ignore[union-attr]
    assert isinstance(execution.integration_connection_ref, IntegrationConnectionRef)
    assert value.model_dump(mode="json", by_alias=True)["capabilities"][
        "reservation.create"
    ]["execution"]["query"] == {"source": {"$expr": "request.source"}}


def test_capability_registry_is_tenant_only() -> None:
    registry = ComponentRegistry()
    register_capability_components(registry)
    assert registry.resolve(
        ComponentAddress(ComponentKind("capabilities.tenant"), TenantScope("t"))
    )
    with pytest.raises(ScopeNotAllowed):
        registry.resolve(
            ComponentAddress(ComponentKind("capabilities.tenant"), PlatformScope())
        )


def test_tool_name_collision_and_binding_normalization_are_deterministic() -> None:
    assert derive_tool_name("x." + "a" * 80).endswith(
        "_" + derive_tool_name("x." + "a" * 80).rsplit("_", 1)[1]
    )
    assert normalize_canonical_input(
        {"phone": "00 421 912 123 456", "custom": "  unchanged  "},
        {"phone": "guest.phone"},
    ) == {"phone": "+421912123456", "custom": "  unchanged  "}
    with pytest.raises(ValidationError, match="duplicate derived tool name"):
        TenantCapabilitiesConfig.model_validate(
            {"capabilities": {"a.b": profile(), "a_b": profile()}}
        )


def test_unsupported_policy_and_invalid_date_binding_are_rejected() -> None:
    with pytest.raises(InvalidComponentValue, match="Availability proof"):
        TenantCapabilitiesConfig.model_validate(
            {
                "capabilities": {
                    "reservation.create": profile(
                        business_policy={"requires_availability_proof": True}
                    )
                }
            }
        )
    broken = profile(
        input_constraints=[
            {"kind": "date_range", "start": "guest.phone", "end": "stay.check_out"}
        ]
    )
    with pytest.raises(InvalidComponentValue, match="date range fields"):
        TenantCapabilitiesConfig.model_validate(
            {"capabilities": {"reservation.create": broken}}
        )
