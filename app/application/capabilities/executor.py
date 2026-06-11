import uuid
from datetime import datetime
from time import perf_counter

from app.agent.runtime.capability_executor import CapabilityExecution
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityRequest
from app.domain.messages.entities import Message
from app.domain.tool_calls.entities import ToolCall
from app.domain.tool_calls.enums import ToolCallStatus
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.schemas.tool_calls import ToolCallResponse
from app.tenants.schemas import TenantContext


class BackendCapabilityExecutor:
    def __init__(
        self,
        *,
        tenant_context: TenantContext,
        message: Message,
        capability_router: CapabilityRouter,
        tool_call_repository: ToolCallRepository,
    ):
        self.tenant_context = tenant_context
        self.message = message
        self.capability_router = capability_router
        self.tool_call_repository = tool_call_repository

    def execute(self, capability_request: CapabilityRequest) -> CapabilityExecution:
        execution_request = self._with_execution_context(capability_request)
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
        return CapabilityExecution(
            request=execution_request,
            result=capability_result,
            tool_call=self._to_tool_call_response(tool_call),
        )

    def _with_execution_context(self, capability_request: CapabilityRequest) -> CapabilityRequest:
        execution_input = {
            **capability_request.input,
            "tenant_id": self.message.tenant_id,
            "message_id": self.message.id,
            "conversation_id": self.message.conversation_id,
            "source_channel": self.message.channel,
        }
        return capability_request.model_copy(update={"input": execution_input})

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
