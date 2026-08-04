from datetime import date
from uuid import UUID, uuid4

import pytest
from backend_core.modules.capabilities.domain import (
    REGISTRY,
    CapabilityValidationError,
    compile_plan,
    definition,
    normalize_input,
    runtime_definition,
    validate_agent_input,
    validate_agent_schema,
    validate_business_input,
)
from contracts import TenantCapabilityProfile


def schema(*, phone: bool = False) -> dict[str, object]:
    properties: dict[str, object] = {
        "guest_name": {
            "type": "string",
            "minLength": 1,
            "x-canonical-field": "guest.name",
        },
        "check_in": {
            "type": "string",
            "format": "date",
            "x-canonical-field": "stay.check_in",
        },
        "check_out": {
            "type": "string",
            "format": "date",
            "x-canonical-field": "stay.check_out",
        },
    }
    required = ["guest_name", "check_in", "check_out"]
    if phone:
        properties["phone"] = {
            "type": "string",
            "minLength": 1,
            "x-canonical-field": "guest.phone",
        }
        required.insert(1, "phone")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def profile(mapping: str, *, phone: bool = False) -> TenantCapabilityProfile:
    fixture = {
        "guest_name": "Fixture Guest",
        "check_in": "2030-08-12",
        "check_out": "2030-08-15",
    }
    if phone:
        fixture["phone"] = "+421900000000"
    return TenantCapabilityProfile.model_validate(
        {
            "enabled": True,
            "semantic_version": 1,
            "description": "Submit a reservation request.",
            "announcement": "I will submit your reservation request now.",
            "agent_input_schema": schema(phone=phone),
            "execution": {
                "plan_type": "google_sheets.append_values.v1",
                "connection_id": str(uuid4()),
                "spreadsheet_id": "sheet",
                "sheet_name": "Reservations",
                "append_range": "A:G",
                "value_input_option": "RAW",
                "idempotency": {"lookup_range": "A:A", "operation_id_column_index": 0},
                "request_mapping": mapping,
            },
            "validation_fixtures": [fixture, fixture],
        }
    )


def compile_row(
    capability: TenantCapabilityProfile, payload: dict[str, object]
) -> list[object]:
    validate_agent_schema(
        capability.agent_input_schema, definition("reservation.submit_request", 1)
    )
    validate_agent_input(capability.agent_input_schema, payload)
    canonical = validate_business_input(
        normalize_input(capability.agent_input_schema, payload),
        "Europe/Bratislava",
        today=date(2026, 8, 4),
    )
    plan = compile_plan(
        capability,
        canonical,
        operation_id=UUID("00000000-0000-0000-0000-000000000001"),
        call_id=uuid4(),
        tool_call_id="tool-call",
        credential_ref="tenant-sheets",
    )
    return plan.rows[0]


def test_registry_is_code_owned_and_has_one_capability() -> None:
    assert set(REGISTRY) == {("reservation.submit_request", 1)}
    with pytest.raises(CapabilityValidationError):
        definition("reservation.create", 1)


def test_two_tenant_profiles_compile_with_the_same_code() -> None:
    tenant_a = profile(
        '{"rows": [[metadata.operation_id, business.guest.name, business.stay.check_in, business.stay.check_out]]}'
    )
    tenant_b = profile(
        '{"rows": [[metadata.operation_id, business.stay.check_in, business.stay.check_out, business.guest.name, business.guest.phone, "new", "voice_agent"]]}',
        phone=True,
    )
    assert compile_row(
        tenant_a,
        {"guest_name": "Alice", "check_in": "2026-08-12", "check_out": "2026-08-15"},
    ) == ["00000000-0000-0000-0000-000000000001", "Alice", "2026-08-12", "2026-08-15"]
    assert compile_row(
        tenant_b,
        {
            "guest_name": "Bob",
            "phone": "+421 900 000 000",
            "check_in": "2026-08-20",
            "check_out": "2026-08-22",
        },
    ) == [
        "00000000-0000-0000-0000-000000000001",
        "2026-08-20",
        "2026-08-22",
        "Bob",
        "+421900000000",
        "new",
        "voice_agent",
    ]
    assert (
        runtime_definition("reservation.submit_request", tenant_a)
        .input_schema["properties"]["guest_name"]
        .get("x-canonical-field")
        is None
    )  # type: ignore[index,union-attr]


def test_schema_rejects_remote_refs_and_duplicate_canonical_fields() -> None:
    invalid = schema()
    invalid["properties"]["alias"] = {  # type: ignore[index]
        "type": "string",
        "x-canonical-field": "guest.name",
    }
    with pytest.raises(CapabilityValidationError, match="more than once"):
        validate_agent_schema(invalid, definition("reservation.submit_request", 1))
    remote = schema()
    remote["properties"]["guest_name"]["$ref"] = "https://example.com/schema"  # type: ignore[index]
    with pytest.raises(CapabilityValidationError, match="local"):
        validate_agent_schema(remote, definition("reservation.submit_request", 1))


def test_custom_fields_are_explicit_and_invalid_mapping_output_is_rejected() -> None:
    custom_schema = schema()
    custom_schema["properties"]["parking"] = {  # type: ignore[index]
        "type": "boolean",
        "x-custom-field": "parking_required",
    }
    payload = {
        "guest_name": "Alice",
        "check_in": "2026-08-12",
        "check_out": "2026-08-15",
        "parking": True,
    }
    validate_agent_schema(
        custom_schema,
        definition("reservation.submit_request", 1),
    )
    assert normalize_input(custom_schema, payload)["custom"] == {
        "parking_required": True
    }
    invalid = profile('{"rows": [[business.guest.name]]}')
    with pytest.raises(CapabilityValidationError, match="operation_id"):
        compile_row(
            invalid,
            {
                "guest_name": "Alice",
                "check_in": "2026-08-12",
                "check_out": "2026-08-15",
            },
        )
    multiple = profile('{"rows": [[metadata.operation_id], [metadata.operation_id]]}')
    with pytest.raises(CapabilityValidationError, match="exactly one row"):
        compile_row(
            multiple,
            {
                "guest_name": "Alice",
                "check_in": "2026-08-12",
                "check_out": "2026-08-15",
            },
        )
