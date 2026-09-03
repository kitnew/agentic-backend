from uuid import UUID

from contracts import ExecutionPlan, RuntimeIntegrationMaterial
from pydantic import TypeAdapter, ValidationError

from backend_core.platform.control_plane import ControlPlaneClient
from backend_core.runtime.capabilities.repository import CapabilityInvocationRepository

_execution_plan = TypeAdapter(ExecutionPlan)


class IntegrationConnectionError(ValueError):
    pass


class CapabilityIntegrationResolver:
    def __init__(
        self,
        invocations: CapabilityInvocationRepository,
        control_plane: ControlPlaneClient,
    ) -> None:
        self._invocations = invocations
        self._control_plane = control_plane

    async def resolve(
        self,
        invocation_id: UUID,
        job_id: UUID,
        *,
        call_id: UUID | None = None,
        execution_snapshot_id: UUID | None = None,
    ) -> RuntimeIntegrationMaterial:
        invocation = await self._invocations.get(invocation_id)
        if (
            invocation is None
            or invocation.job_id != job_id
            or (call_id is not None and invocation.call_id != call_id)
            or (
                execution_snapshot_id is not None
                and invocation.execution_snapshot_id != execution_snapshot_id
            )
        ):
            raise IntegrationConnectionError("capability_not_found")
        try:
            plan = _execution_plan.validate_python(invocation.execution_plan)
            integration_id = plan.integration_id
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise IntegrationConnectionError("capability_plan_invalid") from error
        return await self._control_plane.integration_execution_material(
            invocation.tenant_id, integration_id
        )
