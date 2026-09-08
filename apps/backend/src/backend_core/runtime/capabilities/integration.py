from uuid import UUID

from contracts import IntegrationExecutionMaterial, WorkerExecutionContext
from pydantic import ValidationError

from backend_core.platform.control_plane import ControlPlaneClient
from backend_core.runtime.capabilities.repository import CapabilityInvocationRepository


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
        execution_id: UUID,
        call_id: UUID | None = None,
    ) -> IntegrationExecutionMaterial:
        invocation = await self._invocations.get(invocation_id)
        if (
            invocation is None
            or invocation.job_id != job_id
            or (call_id is not None and invocation.call_id != call_id)
            or invocation.execution_id != execution_id
        ):
            raise IntegrationConnectionError("capability_not_found")
        try:
            context = WorkerExecutionContext.model_validate(invocation.worker_context)
            integration = context.integration
            integration_key = integration["semantic_key"] if integration else None
            if not isinstance(integration_key, str):
                raise TypeError
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise IntegrationConnectionError("capability_context_invalid") from error
        return await self._control_plane.integration_execution_material(
            invocation.execution_id, integration_key
        )
