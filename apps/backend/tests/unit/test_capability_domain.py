from uuid import UUID, uuid4

import pytest
from backend_core.runtime.capabilities.domain import (
    CapabilityValidationError,
    compile_plan,
    enforce_input_constraints,
    normalize_input,
    resolve_capability,
    semantic_result,
    validate_agent_input,
)
from backend_core.runtime.capabilities.execution import ExecutionOutcome
from contracts import (
    CapabilityBusinessPolicy,
    CapabilityDateRangeConstraint,
    HttpExecution,
    RuntimeCapabilityInputConstraint,
    TenantCapabilityProfile,
)


def schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["guest_name", "check_in", "note"],
        "properties": {
            "guest_name": {"type": "string", "minLength": 1},
            "check_in": {"type": "string", "format": "date"},
            "note": {"type": "string"},
        },
    }


def profile(
    *,
    input_schema: dict[str, object] | None = None,
    bindings: dict[str, str] | None = None,
    request_mapping: object | None = None,
    result_schema: dict[str, object] | None = None,
) -> TenantCapabilityProfile:
    return TenantCapabilityProfile(
        enabled=True,
        semantic_version=1,
        description="Tenant-provided capability",
        announcement="Working on it.",
        agent_input_schema=input_schema if input_schema is not None else schema(),
        bindings=(
            bindings
            if bindings is not None
            else {
                "guest_name": "guest.name",
                "check_in": "stay.check_in",
                "note": "custom.note",
            }
        ),
        execution=HttpExecution(
            connection_id=uuid4(),
            method="POST",
            request={
                "codec": "json",
                "mapping": request_mapping
                or {
                    "guest": {"$expr": "business.guest.name"},
                    "date": {"$expr": "business.stay.check_in"},
                    "note": {"$expr": "business.custom.note"},
                },
            },
            response={"codec": "json", "mapping": None},
            timeout_seconds=10,
            result_schema=result_schema,
        ),
    )


def test_arbitrary_tenant_capability_resolves_to_runtime_metadata() -> None:
    capability = profile()

    resolved = resolve_capability("tenant.booking-check", capability)

    assert resolved.semantic_key == "tenant.booking-check"
    assert resolved.semantic_version == 1
    assert resolved.tool_name == "tenant_booking-check"
    assert resolved.description == capability.description
    assert resolved.input_schema == capability.agent_input_schema


def test_long_tool_name_is_stable_and_valid() -> None:
    semantic_key = f"tenant.{'a' * 120}"

    first = resolve_capability(semantic_key, profile()).tool_name
    second = resolve_capability(semantic_key, profile()).tool_name

    assert first == second
    assert len(first) <= 64


@pytest.mark.parametrize(
    "semantic_key", ["Reservation.lookup", "reservation:lookup", "a" * 129]
)
def test_invalid_semantic_key_is_rejected(semantic_key: str) -> None:
    with pytest.raises(CapabilityValidationError) as error:
        resolve_capability(semantic_key, profile())
    assert error.value.code == "invalid_semantic_key"


def test_invalid_semantic_version_is_rejected() -> None:
    capability = profile().model_copy(update={"semantic_version": 0})
    with pytest.raises(CapabilityValidationError) as error:
        resolve_capability("tenant.lookup", capability)
    assert error.value.code == "invalid_semantic_version"


def test_invalid_schema_binding_mapping_and_result_schema_are_rejected() -> None:
    with pytest.raises(CapabilityValidationError) as schema_error:
        resolve_capability(
            "tenant.invalid_schema",
            profile(input_schema={"type": "array"}, bindings={}),
        )
    assert schema_error.value.code == "invalid_json_schema"

    with pytest.raises(CapabilityValidationError) as binding_error:
        resolve_capability(
            "tenant.invalid_binding",
            profile(bindings={"guest_name": "unknown.field"}),
        )
    assert binding_error.value.code == "unknown_domain_field"

    with pytest.raises(CapabilityValidationError) as mapping_error:
        resolve_capability(
            "tenant.invalid_mapping",
            profile(request_mapping={"value": {"$expr": "("}}),
        )
    assert mapping_error.value.code == "invalid_mapping_expression"

    with pytest.raises(CapabilityValidationError) as result_error:
        resolve_capability(
            "tenant.invalid_result",
            profile(result_schema={"type": "invalid"}),
        )
    assert result_error.value.code == "invalid_result_schema"


def test_remote_refs_and_schema_extensions_are_rejected() -> None:
    for input_schema in (
        {
            **schema(),
            "properties": {
                **schema()["properties"],
                "remote": {"$ref": "https://example.com/schema"},
            },
        },
        {
            **schema(),
            "properties": {
                **schema()["properties"],
                "legacy": {"type": "string", "x-canonical-field": "guest.name"},
            },
        },
    ):
        with pytest.raises(CapabilityValidationError):
            resolve_capability(
                "tenant.invalid_schema_extension",
                profile(input_schema=input_schema),
            )


def test_http_plan_uses_declarative_bindings_and_semantic_identity() -> None:
    capability = profile()
    agent_input = {
        "guest_name": "Anna",
        "check_in": "2026-08-19",
        "note": "late arrival",
    }
    validate_agent_input(capability.agent_input_schema, agent_input)
    canonical = normalize_input(agent_input, capability.bindings)

    plan = compile_plan(
        capability,
        canonical,
        operation_id=UUID("00000000-0000-0000-0000-000000000001"),
        call_id=uuid4(),
        tool_call_id="tool-call",
        integration_id=capability.execution.connection_id,
        semantic_key="reservation.check_reservation",
    )

    assert plan.capability == {
        "semantic_key": "reservation.check_reservation",
        "semantic_version": 1,
    }
    assert plan.payload == {
        "guest": "Anna",
        "date": "2026-08-19",
        "note": "late arrival",
    }


def test_generic_result_processing_returns_provider_data() -> None:
    assert semantic_result(ExecutionOutcome(data={"status": "confirmed"})) == {
        "status": "confirmed"
    }
    assert semantic_result(ExecutionOutcome(reference="ignored")) == {}


def test_canonical_normalization_is_binding_target_specific() -> None:
    value = normalize_input(
        {
            "name": "  Anna Pasuchová  ",
            "phone": "00 421 (918) 961-454",
            "email": "  anna@example.com  ",
            "UserID": " 00 421 900 000 000 ",
        },
        {
            "name": "guest.name",
            "phone": "guest.phone",
            "email": "guest.email",
        },
    )

    assert value["guest"] == {
        "name": "Anna Pasuchová",
        "phone": "+421918961454",
        "email": "anna@example.com",
    }
    assert value["custom"]["UserID"] == " 00 421 900 000 000 "


def test_invalid_canonical_phone_is_rejected() -> None:
    with pytest.raises(CapabilityValidationError, match="E.164"):
        normalize_input({"phone": "not-a-phone"}, {"phone": "guest.phone"})


def test_date_range_constraints_validate_order_and_tenant_timezone() -> None:
    constraints = [
        RuntimeCapabilityInputConstraint(
            start="stay.check_in", end="stay.check_out", start_not_in_past=True
        )
    ]

    with pytest.raises(CapabilityValidationError, match="after check-in"):
        enforce_input_constraints(
            {"stay": {"check_in": "2030-01-02", "check_out": "2030-01-01"}},
            "Europe/Bratislava",
            constraints,
        )
    with pytest.raises(CapabilityValidationError, match="past"):
        enforce_input_constraints(
            {"stay": {"check_in": "2000-01-01", "check_out": "2000-01-02"}},
            "Pacific/Honolulu",
            constraints,
        )


def test_invalid_input_constraint_reference_is_rejected() -> None:
    capability = profile(
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["check_in", "check_out"],
            "properties": {
                "check_in": {"type": "string", "format": "date"},
                "check_out": {"type": "string", "format": "date"},
            },
        },
        bindings={
            "check_in": "stay.check_in",
            "check_out": "stay.check_out",
        },
    ).model_copy(
        update={
            "input_constraints": [
                CapabilityDateRangeConstraint(
                    start="stay.check_in",
                    end="stay.check_out",
                    start_not_in_past=True,
                )
            ]
        }
    )
    with pytest.raises(CapabilityValidationError, match="not bound"):
        resolve_capability(
            "tenant.invalid_constraint",
            capability.model_copy(
                update={"bindings": {"check_in": "stay.check_in"}}
            ),
        )


def test_availability_proof_is_rejected_until_enforced() -> None:
    capability = profile().model_copy(
        update={
            "business_policy": CapabilityBusinessPolicy(
                requires_availability_proof=True,
                availability_proof_ttl_seconds=10,
            )
        }
    )
    with pytest.raises(CapabilityValidationError, match="not implemented") as error:
        resolve_capability("tenant.availability", capability)
    assert error.value.code == "unsupported_business_policy"
