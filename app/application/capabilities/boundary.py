import inspect
import logging
from time import perf_counter
from typing import Protocol

from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import (
    CapabilityCommand,
    CapabilityExecutionResult,
    CapabilityExecutionStatus,
    CapabilityRequest,
    CapabilityStatus,
)
from app.tenants.loader import TenantConfigLoader
from app.tenants.schemas import TenantContext


logger = logging.getLogger(__name__)


class CapabilityExecutor(Protocol):
    async def execute(self, command: CapabilityCommand) -> CapabilityExecutionResult:
        pass


class InProcessCapabilityExecutor:
    def __init__(
        self,
        *,
        tenant_config_loader: TenantConfigLoader | None = None,
        capability_router: CapabilityRouter | None = None,
    ):
        self.tenant_config_loader = tenant_config_loader or TenantConfigLoader()
        self.capability_router = capability_router or CapabilityRouter()

    async def execute(self, command: CapabilityCommand) -> CapabilityExecutionResult:
        started_at = perf_counter()
        try:
            tenant_context = self.tenant_config_loader.load(command.tenant_id)
            result = await self._execute_local(tenant_context, command)
            normalized = self._normalize_result(
                command,
                result,
                execution_duration_ms=self._duration_ms(started_at),
            )
        except Exception as exc:
            normalized = CapabilityExecutionResult(
                command_id=command.command_id,
                status=CapabilityExecutionStatus.FAILED,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
                execution_duration_ms=self._duration_ms(started_at),
                metadata={
                    **command.metadata,
                    "capability_name": self._legacy_name(command),
                },
            )

        self._log_result(command, normalized)
        return normalized

    async def _execute_local(
        self,
        tenant_context: TenantContext,
        command: CapabilityCommand,
    ):
        request = CapabilityRequest(
            name=self._legacy_name(command),
            input=command.payload,
            metadata={
                **command.metadata,
                "command_id": command.command_id,
                **({"idempotency_key": command.idempotency_key} if command.idempotency_key else {}),
            },
        )
        result = self.capability_router.execute(tenant_context, request)
        if inspect.isawaitable(result):
            return await result
        return result

    def _normalize_result(
        self,
        command: CapabilityCommand,
        legacy_result,
        *,
        execution_duration_ms: int,
    ) -> CapabilityExecutionResult:
        status = (
            CapabilityExecutionStatus.SUCCESS
            if legacy_result.status == CapabilityStatus.SUCCESS
            else CapabilityExecutionStatus.FAILED
        )
        return CapabilityExecutionResult(
            command_id=command.command_id,
            status=status,
            result=legacy_result.output,
            error_code=legacy_result.status.value if status == CapabilityExecutionStatus.FAILED else None,
            error_message=legacy_result.error,
            execution_duration_ms=execution_duration_ms,
            metadata={
                **command.metadata,
                "capability_name": legacy_result.name,
                "provider": legacy_result.provider,
                "legacy_status": legacy_result.status.value,
                "user_message": legacy_result.user_message,
            },
        )

    def _log_result(
        self,
        command: CapabilityCommand,
        result: CapabilityExecutionResult,
    ) -> None:
        logger.info(
            "Capability execution finished",
            extra={
                "command_id": command.command_id,
                "tenant_id": command.tenant_id,
                "conversation_id": command.conversation_id,
                "call_session_id": command.call_session_id,
                "capability": command.capability,
                "action": command.action,
                "status": result.status.value,
                "duration": result.execution_duration_ms,
            },
        )

    def _legacy_name(self, command: CapabilityCommand) -> str:
        return command.metadata.get("legacy_capability_name") or f"{command.capability}.{command.action}"

    def _duration_ms(self, started_at: float) -> int:
        return int((perf_counter() - started_at) * 1000)
