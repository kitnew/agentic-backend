import uuid
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any

from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus
from app.domain.messages.entities import Message
from app.domain.tool_calls.entities import ToolCall
from app.domain.tool_calls.enums import ToolCallStatus
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.schemas.tool_calls import ToolCallResponse
from app.tenants.schemas import TenantContext


@dataclass
class CapabilityExecution:
    request: CapabilityRequest
    result: CapabilityResult
    tool_call: ToolCallResponse | None


class MissingCapabilityLedger:
    def get_by_idempotency_key(self, idempotency_key: str):
        return None

    def reserve(self, **kwargs):
        return None

    def mark_finished(self, **kwargs) -> None:
        return None


CapabilityLedger = Any


class BackendCapabilityExecutor:
    def __init__(
        self,
        *,
        tenant_context: TenantContext,
        message: Message,
        capability_router: CapabilityRouter,
        tool_call_repository: ToolCallRepository,
        capability_ledger: CapabilityLedger | None = None,
    ):
        self.tenant_context = tenant_context
        self.message = message
        self.capability_router = capability_router
        self.tool_call_repository = tool_call_repository
        self.capability_ledger = capability_ledger or MissingCapabilityLedger()

    def execute(self, capability_request: CapabilityRequest) -> CapabilityExecution:
        idempotency_key = (capability_request.metadata or {}).get("idempotency_key")
        existing_call = (
            self.capability_ledger.get_by_idempotency_key(idempotency_key)
            if idempotency_key
            else None
        )
        if existing_call and existing_call.status == CapabilityStatus.SUCCESS.value:
            return self._existing_success_execution(capability_request, existing_call)

        reserved_call = None
        if idempotency_key:
            reserved_call = self.capability_ledger.reserve(
                idempotency_key=idempotency_key,
                tenant_id=self.message.tenant_id,
                conversation_id=self.message.conversation_id,
                task_id=(capability_request.metadata or {}).get("task_id"),
                capability_name=capability_request.name,
                input_hash=(capability_request.metadata or {}).get("input_hash") or "",
                metadata=capability_request.metadata,
            )

        execution_request = self._with_execution_context(capability_request, reserved_call_id=reserved_call.id if reserved_call else None)
        started_at = perf_counter()
        capability_result = self.capability_router.execute(self.tenant_context, execution_request)
        latency_ms = int((perf_counter() - started_at) * 1000)

        tool_call = ToolCall(
            id=str(uuid.uuid4()),
            tenant_id=self.message.tenant_id,
            message_id=self.message.id,
            conversation_id=self.message.conversation_id,
            capability_name=execution_request.name,
            provider=capability_result.provider,
            input=execution_request.input,
            output=capability_result.output,
            status=ToolCallStatus(capability_result.status),
            error=capability_result.error,
            latency_ms=latency_ms,
            created_at=datetime.now(),
        )
        self.tool_call_repository.create(tool_call)
        if reserved_call:
            self.capability_ledger.mark_finished(
                capability_call_id=reserved_call.id,
                status=capability_result.status.value,
                result=capability_result,
                tool_call_id=tool_call.id,
            )
        return CapabilityExecution(
            request=execution_request,
            result=capability_result,
            tool_call=self._to_tool_call_response(tool_call),
        )

    def _with_execution_context(
        self,
        capability_request: CapabilityRequest,
        *,
        reserved_call_id: str | None,
    ) -> CapabilityRequest:
        execution_input = {
            **capability_request.input,
            "tenant_id": self.message.tenant_id,
            "message_id": self.message.id,
            "conversation_id": self.message.conversation_id,
            "source_channel": self.message.channel,
        }
        if reserved_call_id:
            execution_input["capability_call_id"] = reserved_call_id
        metadata = {**(capability_request.metadata or {})}
        if reserved_call_id:
            metadata["capability_call_id"] = reserved_call_id
        return capability_request.model_copy(update={"input": execution_input, "metadata": metadata})

    def _existing_success_execution(
        self,
        capability_request: CapabilityRequest,
        existing_call,
    ) -> CapabilityExecution:
        result = (
            CapabilityResult.model_validate(existing_call.result)
            if existing_call.result
            else CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.SKIPPED,
                provider="capability_ledger",
                user_message="Táto požiadavka už bola spracovaná.",
            )
        )
        request = capability_request.model_copy(
            update={
                "metadata": {
                    **(capability_request.metadata or {}),
                    "capability_call_id": existing_call.id,
                    "idempotency_reused": True,
                }
            }
        )
        return CapabilityExecution(request=request, result=result, tool_call=None)

    def _to_tool_call_response(self, tool_call: ToolCall) -> ToolCallResponse:
        return ToolCallResponse(
            id=tool_call.id,
            tenant_id=tool_call.tenant_id,
            message_id=tool_call.message_id,
            conversation_id=tool_call.conversation_id,
            capability_name=tool_call.capability_name,
            provider=tool_call.provider,
            input=tool_call.input,
            output=tool_call.output,
            status=tool_call.status,
            error=tool_call.error,
            latency_ms=tool_call.latency_ms,
            created_at=tool_call.created_at,
        )
