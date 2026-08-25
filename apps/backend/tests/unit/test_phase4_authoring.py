import pytest
from backend_core.modules.tenants.authoring import (
    integration_readiness_warnings,
    translate_capabilities,
    translate_post_call,
)
from backend_core.modules.tenants.discovery_router import capabilities, post_call
from backend_core.runtime.capabilities.domain import (
    CANONICAL_FIELDS,
    CapabilityValidationError,
    validate_bindings,
    validate_result_for_plan,
)
from contracts import HttpRequestPlanV1, HttpRequestResult
from contracts.domain_catalog import CANONICAL_FIELDS as SHARED_CANONICAL_FIELDS
from contracts.domain_catalog import (
    CapabilityDiscoveryResponse,
    PostCallDiscoveryResponse,
)
from pydantic import ValidationError


def _schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["check_in", "check_out", "room_type", "room_count"],
        "properties": {
            "check_in": {"type": "string"},
            "check_out": {"type": "string"},
            "room_type": {"type": "integer"},
            "room_count": {"type": "integer"},
        },
    }


def test_explicit_binding_accepts_canonical_and_custom_without_schema_extensions() -> (
    None
):
    validate_bindings(
        _schema(),
        {
            "check_in": "stay.check_in",
            "check_out": "stay.check_out",
            "room_type": "allocation.room_type",
            "room_count": "allocation.room_count",
        },
    )
    validate_bindings(
        {
            **_schema(),
            "properties": {**_schema()["properties"], "ref": {"type": "string"}},
        },
        {
            "check_in": "stay.check_in",
            "check_out": "stay.check_out",
            "room_type": "allocation.room_type",
            "room_count": "allocation.room_count",
            "ref": "custom.reservation_number",
        },
    )


def test_explicit_binding_rejects_unknown_field_and_type_mismatch() -> None:
    with pytest.raises(CapabilityValidationError, match="Unknown canonical"):
        validate_bindings(
            _schema(),
            {
                "check_in": "stay.check_in",
                "check_out": "stay.check_out",
                "room_type": "allocation.unknown",
                "room_count": "allocation.room_count",
            },
        )
    with pytest.raises(CapabilityValidationError, match="incompatible"):
        validate_bindings(
            {
                **_schema(),
                "properties": {
                    **_schema()["properties"],
                    "room_count": {"type": "string"},
                },
            },
            {
                "check_in": "stay.check_in",
                "check_out": "stay.check_out",
                "room_type": "allocation.room_type",
                "room_count": "allocation.room_count",
            },
        )


@pytest.mark.asyncio
async def test_discovery_uses_backend_semantic_and_artifact_sources() -> None:
    capability = await capabilities()
    post_call_response = await post_call()
    assert isinstance(capability, CapabilityDiscoveryResponse)
    assert capability.semantics == []
    assert "business.guest.name" in {item.path for item in capability.mapping_context}
    assert {
        item.path.removeprefix("business.")
        for item in capability.mapping_context
        if item.path.startswith("business.") and not item.path.endswith(".*")
    } == set(CANONICAL_FIELDS)
    assert CANONICAL_FIELDS is SHARED_CANONICAL_FIELDS
    assert isinstance(post_call_response, PostCallDiscoveryResponse)
    assert {item.artifact for item in post_call_response.artifacts} == {
        "transcript",
        "call_recording",
        "call_summary",
    }


def test_result_schema_validates_final_mapped_result() -> None:
    plan = HttpRequestPlanV1(
        integration_id="11111111-1111-1111-1111-111111111111",
        operation_id="22222222-2222-2222-2222-222222222222",
        method="GET",
        timeout_seconds=5,
        result_schema={
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"type": "string"}},
        },
    )
    result = HttpRequestResult(
        result_type="http.request.v1",
        status="succeeded",
        operation_id=plan.operation_id,
        data={"status": "confirmed"},
    )
    assert validate_result_for_plan(plan.model_dump(mode="json"), result).plan_type == "http.request.v1"


def test_operator_capability_rejects_legacy_metadata_and_does_not_require_version_or_fixtures() -> None:
    from contracts.authoring import TenantCapabilityAuthoring
    from contracts.http_operation import HttpOperation

    value = TenantCapabilityAuthoring(
        description="Check availability",
        announcement={"before": "Checking"},
        agent_input_schema={"type": "object"},
        bindings={},
        execution=HttpOperation(connection="previo", method="GET", timeout_seconds=5),
    )
    assert "semantic_version" not in value.model_dump()
    assert "validation_fixtures" not in value.model_dump()
    with pytest.raises(ValidationError):
        TenantCapabilityAuthoring.model_validate(
            {
                **value.model_dump(),
                "x-canonical-field": "guest.name",
                "mapping_engine": "jsonata-python",
            }
        )


@pytest.mark.asyncio
async def test_disabled_existing_connection_is_warning_only() -> None:
    class Connections:
        async def get_by_key(self, tenant_id, key):
            return type("Connection", (), {"enabled": False, "id": "connection-id"})()

    operation = type("Operation", (), {"connection": "previo"})()
    warnings = await integration_readiness_warnings([operation], object(), Connections())
    assert warnings[0]["code"] == "integration_not_ready"

    class DisabledAuthoringConnections(Connections):
        async def get_by_key(self, tenant_id, key):
            return type("Connection", (), {"enabled": False, "id": "11111111-1111-1111-1111-111111111111"})()

    # Translation remains valid; readiness is a live warning, not a save/publish blocker.
    from contracts.authoring import (
        TenantCapabilitiesAuthoring,
        TenantCapabilityAuthoring,
    )
    from contracts.http_operation import HttpOperation

    value = TenantCapabilitiesAuthoring(
        capabilities={
            "reservation.check_availability": TenantCapabilityAuthoring(
                description="Check availability",
                announcement="Checking",
                agent_input_schema=_schema(),
                bindings={
                    "check_in": "stay.check_in",
                    "check_out": "stay.check_out",
                    "room_type": "allocation.room_type",
                    "room_count": "allocation.room_count",
                },
                execution=HttpOperation(connection="previo", method="GET", timeout_seconds=5),
            )
        }
    )
    translated = await translate_capabilities(value, tenant_id=object(), connections=DisabledAuthoringConnections())
    assert translated.capabilities["reservation.check_availability"].execution.connection_id


@pytest.mark.asyncio
async def test_post_call_declared_input_reaches_mapping_template() -> None:
    from contracts.authoring import (
        TenantPostCallActionAuthoring,
        TenantPostCallAuthoring,
    )
    from contracts.http_operation import HttpOperation
    from contracts.tenant_components import PostCallActionInput

    class Connections:
        async def get_by_key(self, tenant_id, key):
            return type("Connection", (), {"id": "11111111-1111-1111-1111-111111111111"})()

    value = TenantPostCallAuthoring(
        actions=[
            TenantPostCallActionAuthoring(
                action_id="send_transcript",
                inputs={"transcript": PostCallActionInput(artifact="transcript", representation="plain_text")},
                execution=HttpOperation(
                    connection="customer-webhook",
                    method="POST",
                    timeout_seconds=5,
                    request={"codec": "json", "mapping": {"transcript": {"$expr": "inputs.transcript"}}},
                ),
            )
        ]
    )
    translated = await translate_post_call(value, tenant_id=object(), connections=Connections())
    mapping = translated.actions[0].execution.request.mapping
    assert mapping["transcript"]["$expr"] == "inputs.transcript"
