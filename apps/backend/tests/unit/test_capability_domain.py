from datetime import date
from uuid import UUID, uuid4

import pytest
from backend_core.runtime.capabilities.domain import (
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
from contracts import (
    ManagedWebhookExecution,
    ManagedWebhookPostJsonPlan,
    TenantCapabilityProfile,
)


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
                "mapping_language": "jsonata",
                "mapping_contract_version": 1,
                "mapping_engine": "jsonata-python",
                "mapping_engine_version": "0.7.0",
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
    capability: TenantCapabilityProfile,
    payload: dict[str, object],
    caller_phone: str = "",
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
        integration_id=uuid4(),
        caller_phone=caller_phone,
    )
    return plan.rows[0]


def test_registry_is_code_owned_and_has_one_capability() -> None:
    assert set(REGISTRY) == {
        ("reservation.submit_request", 1),
        ("reservation.check_availability", 1),
    }
    with pytest.raises(CapabilityValidationError):
        definition("reservation.create", 1)


def test_check_availability_definition_is_registered() -> None:
    capability = definition("reservation.check_availability", 1)
    assert capability.tool_name == "reservation_check_availability"
    assert capability.required_fields == frozenset(
        {
            "stay.check_in",
            "stay.check_out",
            "allocation.room_type",
            "allocation.room_count",
        }
    )


def test_check_availability_business_validation_does_not_require_guest_name() -> None:
    canonical = validate_business_input(
        normalize_input(
            {
                "properties": {
                    "check_in": {"x-canonical-field": "stay.check_in"},
                    "check_out": {"x-canonical-field": "stay.check_out"},
                    "room_type": {"x-canonical-field": "allocation.room_type"},
                    "room_count": {"x-canonical-field": "allocation.room_count"},
                }
            },
            {
                "check_in": "2030-08-12",
                "check_out": "2030-08-15",
                "room_type": 1,
                "room_count": 1,
            },
        ),
        "Europe/Bratislava",
        required_fields=definition("reservation.check_availability", 1).required_fields,
        today=date(2030, 8, 1),
    )
    assert canonical["guest"]["name"] is None


def test_managed_webhook_plan_contains_payload_not_provider_details() -> None:
    capability = profile(
        '{"check_in": business.stay.check_in, "guest_name": business.guest.name}'
    ).model_copy(
        update={
            "execution": ManagedWebhookExecution(
                plan_type="managed_webhook.post_json.v1",
                connection_id=uuid4(),
                mapping_language="jsonata",
                mapping_contract_version=1,
                mapping_engine="jsonata-python",
                mapping_engine_version="0.7.0",
                request_mapping='{"check_in": business.stay.check_in, "guest_name": business.guest.name}',
                timeout_seconds=10,
            )
        }
    )
    plan = compile_plan(
        capability,
        {
            "guest": {"name": "Alice", "phone": None, "email": None},
            "stay": {"check_in": "2026-08-12", "check_out": "2026-08-15"},
            "allocation": {"room_type": None, "room_count": None},
            "notes": None,
            "custom": {},
        },
        operation_id=UUID("00000000-0000-0000-0000-000000000001"),
        call_id=uuid4(),
        tool_call_id="tool-call",
        integration_id=uuid4(),
    )
    assert plan.plan_type == "managed_webhook.post_json.v1"
    assert plan.payload == {"check_in": "2026-08-12", "guest_name": "Alice"}
    assert plan.response_contract == "managed_webhook_envelope.v1"
    assert not hasattr(plan, "url")


def test_managed_webhook_response_contract_compiles_into_pinned_plan() -> None:
    capability = profile("{}").model_copy(
        update={
            "execution": ManagedWebhookExecution.model_validate(
                {
                    "plan_type": "managed_webhook.post_json.v1",
                    "connection_id": str(uuid4()),
                    "mapping_language": "jsonata",
                    "mapping_contract_version": 1,
                    "mapping_engine": "jsonata-python",
                    "mapping_engine_version": "0.7.0",
                    "request_mapping": '{"guest_name": business.guest.name}',
                    "response": {
                        "mode": "json",
                        "mapping": '{"status": "created", "request_id": response.body.id}',
                        "output_schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["status"],
                            "properties": {
                                "status": {"type": "string"},
                                "request_id": {"type": "string"},
                            },
                        },
                    },
                    "timeout_seconds": 10,
                }
            )
        }
    )
    plan = compile_plan(
        capability,
        {
            "guest": {"name": "Alice", "phone": None, "email": None},
            "stay": {"check_in": "2026-08-12", "check_out": "2026-08-15"},
            "allocation": {"room_type": None, "room_count": None},
            "notes": None,
            "custom": {},
        },
        operation_id=uuid4(),
        call_id=uuid4(),
        tool_call_id="tool-call",
        integration_id=uuid4(),
    )

    assert isinstance(plan, ManagedWebhookPostJsonPlan)
    assert plan.response_contract == "http_2xx"
    assert plan.response is not None and plan.response.mode == "json"


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
    runtime_schema = runtime_definition(
        "reservation.submit_request", tenant_a
    ).input_schema
    assert "YYYY-MM-DD" in runtime_schema["properties"]["check_in"]["description"]  # type: ignore[index]
    assert "YYYY-MM-DD" in runtime_schema["properties"]["check_out"]["description"]  # type: ignore[index]


def test_pension_grand_row_keeps_phone_types_and_operation_marker() -> None:
    grand_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "guest_name": {"type": "string", "x-canonical-field": "guest.name"},
            "reservation_phone": {
                "type": "string",
                "x-canonical-field": "guest.phone",
            },
            "email": {
                "type": "string",
                "format": "email",
                "x-canonical-field": "guest.email",
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
            "room_type": {
                "type": "integer",
                "enum": [2, 3, 4],
                "x-canonical-field": "allocation.room_type",
            },
            "room_count": {
                "type": "integer",
                "minimum": 1,
                "x-canonical-field": "allocation.room_count",
            },
        },
        "required": [
            "guest_name",
            "reservation_phone",
            "check_in",
            "check_out",
            "room_type",
            "room_count",
        ],
        "additionalProperties": False,
    }
    grand = TenantCapabilityProfile.model_validate(
        {
            "enabled": True,
            "semantic_version": 1,
            "description": "Submit a reservation request.",
            "announcement": "I will submit your reservation request now.",
            "agent_input_schema": grand_schema,
            "business_policy": {"requires_caller_phone": True},
            "execution": {
                "plan_type": "google_sheets.append_values.v1",
                "mapping_language": "jsonata",
                "mapping_contract_version": 1,
                "mapping_engine": "jsonata-python",
                "mapping_engine_version": "0.7.0",
                "connection_id": str(uuid4()),
                "spreadsheet_id": "sheet",
                "sheet_name": "reservations_new",
                "append_range": "A:K",
                "value_input_option": "RAW",
                "idempotency": {"lookup_range": "K:K", "operation_id_column_index": 10},
                "request_mapping": '{"rows": [[business.stay.check_in, business.stay.check_out, business.guest.name, metadata.caller_phone, business.guest.phone, business.guest.email ? business.guest.email : "", business.allocation.room_type, business.allocation.room_count, "", false, metadata.operation_id]]}',
            },
            "validation_fixtures": [
                {
                    "guest_name": "Fixture",
                    "reservation_phone": "+421900000000",
                    "check_in": "2030-01-01",
                    "check_out": "2030-01-02",
                    "room_type": 4,
                    "room_count": 1,
                },
                {
                    "guest_name": "Fixture",
                    "reservation_phone": "+421900000001",
                    "check_in": "2031-01-01",
                    "check_out": "2031-01-02",
                    "room_type": 2,
                    "room_count": 1,
                },
            ],
        }
    )
    row = compile_row(
        grand,
        {
            "guest_name": "Nikita Černý",
            "reservation_phone": "+421944015686",
            "check_in": "2026-08-08",
            "check_out": "2026-08-09",
            "room_type": 4,
            "room_count": 1,
        },
        "+421944015686",
    )
    assert row == [
        "2026-08-08",
        "2026-08-09",
        "Nikita Černý",
        "+421944015686",
        "+421944015686",
        "",
        4,
        1,
        "",
        False,
        "00000000-0000-0000-0000-000000000001",
    ]


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
