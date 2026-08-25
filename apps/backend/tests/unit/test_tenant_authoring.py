from uuid import UUID

import pytest
from backend_core.modules.tenants.authoring import (
    AuthoringTranslationError,
    authoring_value,
    semantic_plan,
    translate_capabilities,
)
from contracts.authoring import TenantCapabilitiesAuthoring, TenantCapabilityAuthoring
from contracts.http_operation import HttpOperation
from contracts.tenant_components import HttpExecution, TenantCapabilitiesConfig


class _Connections:
    async def get_by_key(self, tenant_id: UUID, key: str):
        if key == "check-availability":
            return type(
                "Connection", (), {"id": UUID("11111111-1111-1111-1111-111111111111")}
            )()
        return None


def _value(
    connection: str = "check-availability",
    semantic_key: str = "tenant.check_reservation",
) -> TenantCapabilitiesAuthoring:
    return TenantCapabilitiesAuthoring(
        capabilities={
            semantic_key: TenantCapabilityAuthoring(
                description="availability",
                announcement="checking",
                agent_input_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["check_in", "check_out", "room_type", "room_count"],
                    "properties": {
                        "check_in": {"type": "string"},
                        "check_out": {"type": "string"},
                        "room_type": {"type": "integer"},
                        "room_count": {"type": "integer"},
                    },
                },
                bindings={
                    "check_in": "stay.check_in",
                    "check_out": "stay.check_out",
                    "room_type": "allocation.room_type",
                    "room_count": "allocation.room_count",
                },
                execution=HttpOperation(
                    connection=connection,
                    method="POST",
                    timeout_seconds=10,
                    request={
                        "codec": "json",
                        "mapping": {"room": {"$expr": "business.room"}},
                    },
                ),
            )
        }
    )


@pytest.mark.asyncio
async def test_authoring_connection_is_resolved_and_runtime_metadata_is_private():
    result = await translate_capabilities(
        _value(), tenant_id=UUID(int=1), connections=_Connections()
    )
    execution = result.capabilities["tenant.check_reservation"].execution
    assert execution.connection_id == UUID("11111111-1111-1111-1111-111111111111")
    assert execution.plan_type == "http.request.v1"
    assert "connection_id" not in _value().model_dump()
    assert "mapping_engine" not in _value().model_dump()


@pytest.mark.asyncio
async def test_authoring_missing_connection_is_typed():
    with pytest.raises(AuthoringTranslationError, match="not found") as error:
        await translate_capabilities(
            _value("missing"), tenant_id=UUID(int=1), connections=_Connections()
        )
    assert error.value.code == "integration_not_found"


@pytest.mark.asyncio
async def test_authoring_rejects_invalid_semantic_key_and_mapping() -> None:
    with pytest.raises(AuthoringTranslationError) as key_error:
        await translate_capabilities(
            _value(semantic_key="tenant:lookup"),
            tenant_id=UUID(int=1),
            connections=_Connections(),
        )
    assert key_error.value.code == "invalid_semantic_key"

    value = _value()
    capability = value.capabilities["tenant.check_reservation"]
    assert isinstance(capability, TenantCapabilityAuthoring)
    invalid_operation = capability.execution.model_copy(
        update={
            "request": capability.execution.request.model_copy(
                update={"mapping": {"value": {"$expr": "("}}}
            )
        }
    )
    value.capabilities["tenant.check_reservation"] = capability.model_copy(
        update={"execution": invalid_operation}
    )
    with pytest.raises(AuthoringTranslationError) as mapping_error:
        await translate_capabilities(
            value, tenant_id=UUID(int=1), connections=_Connections()
        )
    assert mapping_error.value.code == "invalid_mapping_expression"


def test_semantic_plan_is_noop_or_reports_replacement():
    assert semantic_plan({"text": "a"}, {"text": "a"})["changes"] == []
    assert semantic_plan({"text": "a"}, {"text": "b"})["changes"][0]["before"] == {
        "text": "a"
    }


@pytest.mark.asyncio
async def test_internal_capability_read_is_translated_to_operator_shape():
    connection_id = UUID("11111111-1111-1111-1111-111111111111")

    class Connections:
        async def get(self, tenant_id, value):
            assert value == connection_id
            return type("Connection", (), {"key": "check-availability"})()

    payload = TenantCapabilitiesConfig(
        capabilities={
            "tenant.check_reservation": {
                "enabled": True,
                "semantic_version": 1,
                "description": "availability",
                "announcement": "checking",
                "agent_input_schema": {"type": "object"},
                "bindings": {},
                "execution": HttpExecution(
                    connection_id=connection_id,
                    method="POST",
                    timeout_seconds=10,
                    request={
                        "codec": "json",
                        "mapping": {"id": {"$expr": "business.id"}},
                    },
                ),
            }
        }
    ).model_dump(mode="json")
    value = await authoring_value(
        "capabilities", payload, tenant_id=UUID(int=1), connections=Connections()
    )
    execution = value.capabilities["tenant.check_reservation"].execution
    assert execution.connection == "check-availability"
    assert "connection_id" not in value.model_dump()
    assert "plan_type" not in value.model_dump()
    assert (
        "semantic_version"
        not in value.model_dump()["capabilities"]["tenant.check_reservation"]
    )
