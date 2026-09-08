from contracts import (
    BackendExecutionContext,
    VoiceExecutionContext,
    WorkerExecutionContext,
)

from backend_core.modules.calls.models import CallSession
from backend_core.platform.control_plane import ControlPlaneClient


class RuntimeContextUnavailableError(ValueError):
    pass


class ExecutionContextReader:
    """Passes immutable Control Plane projections through without reconstruction."""

    def __init__(self, client: ControlPlaneClient) -> None:
        self._client = client

    @staticmethod
    def _execution_id(call: CallSession):
        if call.execution_id is None:
            raise RuntimeContextUnavailableError("call has no execution")
        return call.execution_id

    async def read(self, call: CallSession) -> VoiceExecutionContext:
        return await self._client.voice_context(self._execution_id(call))

    async def worker(
        self, call: CallSession, action_key: str
    ) -> WorkerExecutionContext:
        return await self._client.worker_context(self._execution_id(call), action_key)

    @staticmethod
    def backend(call: CallSession) -> BackendExecutionContext:
        return BackendExecutionContext.model_validate(call.backend_execution_context)
