from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from backend_core.modules.calls.models import CallSessionStatus
from backend_core.runtime.bundle_store import PinnedRuntimeBundle
from backend_core.runtime.capabilities.domain import CapabilityValidationError
from backend_core.runtime.capabilities.service import CapabilityInvocationService
from contracts import (
    CapabilityInvocationRequest,
    RuntimeBundlePayload,
    RuntimeCapabilityBinding,
    RuntimeCapabilityInputConstraint,
    RuntimeCapabilityPolicy,
    RuntimeHttpExecution,
)


class _Calls:
    def __init__(self, call: SimpleNamespace) -> None:
        self.call = call

    async def get(self, call_id):
        return self.call if call_id == self.call.id else None


class _Bundles:
    def __init__(self, tenant_id, bundle: PinnedRuntimeBundle) -> None:
        self.tenant_id = tenant_id
        self.bundle = bundle

    async def tenant_active(self, tenant_id) -> bool:
        return tenant_id == self.tenant_id

    async def get(self, tenant_id, release_id, bundle_id):
        return self.bundle


def _service(
    *,
    schema: dict[str, object],
    bindings: dict[str, str],
    constraints: list[RuntimeCapabilityInputConstraint] | None = None,
    timezone: str = "Europe/Bratislava",
) -> tuple[CapabilityInvocationService, SimpleNamespace]:
    tenant_id = uuid4()
    call = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        tenant_release_id=uuid4(),
        runtime_bundle_id=uuid4(),
        status=CallSessionStatus.CONNECTED,
        caller_phone_e164=None,
    )
    binding = RuntimeCapabilityBinding(
        semantic_key="tenant.runtime_validation",
        semantic_version=1,
        tool_name="tenant_runtime_validation",
        enabled=True,
        input_schema=schema,
        bindings=bindings,
        input_constraints=constraints or [],
        policy=RuntimeCapabilityPolicy(),
        execution=RuntimeHttpExecution(
            connection_id=uuid4(), method="POST", timeout_seconds=10
        ),
    )
    payload = RuntimeBundlePayload.model_construct(
        timezone=timezone,
        capability_bindings=[binding],
    )
    bundle = PinnedRuntimeBundle(
        id=call.runtime_bundle_id,
        payload=payload,
        provenance={},
    )
    return (
        CapabilityInvocationService(
            invocations=None,
            calls=_Calls(call),
            conversations=None,
            connections=None,
            bundles=_Bundles(tenant_id, bundle),
        ),
        call,
    )


@pytest.mark.asyncio
async def test_runtime_path_normalizes_bound_phone_but_not_custom_user_id() -> None:
    service, call = _service(
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["phone", "UserID"],
            "properties": {
                "phone": {"type": "string"},
                "UserID": {"type": "string"},
            },
        },
        bindings={"phone": "guest.phone"},
    )
    request = CapabilityInvocationRequest(
        tool_call_id="tool-call",
        capability="tenant_runtime_validation",
        agent_input={
            "phone": "00421 (918) 123 456",
            "UserID": "00421 (918) 123 456",
        },
    )

    *_, canonical = await service._validate_request(call.id, request)

    assert canonical["guest"]["phone"] == "+421918123456"
    assert canonical["custom"]["UserID"] == "00421 (918) 123 456"

    with pytest.raises(CapabilityValidationError, match="E.164"):
        await service._validate_request(
            call.id,
            request.model_copy(
                update={"agent_input": {"phone": "not-a-phone", "UserID": "ok"}}
            ),
        )


@pytest.mark.asyncio
async def test_runtime_path_uses_tenant_local_date_at_utc_boundary(monkeypatch) -> None:
    from backend_core.runtime.capabilities import domain

    class FrozenDateTime:
        @classmethod
        def now(cls, tz=None):
            current = datetime(2026, 8, 25, 23, 30, tzinfo=UTC)
            return current.astimezone(tz) if tz is not None else current

    monkeypatch.setattr(domain, "datetime", FrozenDateTime)
    service, call = _service(
        schema={
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
        constraints=[
            RuntimeCapabilityInputConstraint(
                start="stay.check_in",
                end="stay.check_out",
                start_not_in_past=True,
            )
        ],
        timezone="Pacific/Kiritimati",
    )

    with pytest.raises(CapabilityValidationError, match="past"):
        await service._validate_request(
            call.id,
            CapabilityInvocationRequest(
                tool_call_id="yesterday",
                capability="tenant_runtime_validation",
                agent_input={
                    "check_in": "2026-08-25",
                    "check_out": "2026-08-26",
                },
            ),
        )

    *_, current = await service._validate_request(
        call.id,
        CapabilityInvocationRequest(
            tool_call_id="today",
            capability="tenant_runtime_validation",
            agent_input={"check_in": "2026-08-26", "check_out": "2026-08-27"},
        ),
    )
    assert current["stay"] == {"check_in": "2026-08-26", "check_out": "2026-08-27"}

    with pytest.raises(CapabilityValidationError, match="after check-in"):
        await service._validate_request(
            call.id,
            CapabilityInvocationRequest(
                tool_call_id="invalid-order",
                capability="tenant_runtime_validation",
                agent_input={
                    "check_in": "2026-08-26",
                    "check_out": "2026-08-26",
                },
            ),
        )
