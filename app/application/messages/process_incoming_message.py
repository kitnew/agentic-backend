import uuid
from datetime import datetime
from time import perf_counter

from app.infrastructure.repositories.message_repository import MessageRepository
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentInput
from app.capabilities.router import CapabilityRouter
from app.domain.tool_calls.entities import ToolCall
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.schemas.messages import CreateMessageRequest, MessageResponse, ProcessMessageResponse
from app.schemas.tool_calls import ToolCallResponse
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageStatus, MessageRole
from app.tenants.loader import TenantConfigLoader

class ProcessIncomingMessage:
    """
    Orchestration use-case class to handle incoming messages.
    """
    def __init__(
        self,
        message_repository: MessageRepository,
        agent_runtime: AgentRuntime,
        tenant_config_loader: TenantConfigLoader,
        capability_router: CapabilityRouter,
        tool_call_repository: ToolCallRepository,
    ):
        self.message_repository = message_repository
        self.agent_runtime = agent_runtime
        self.tenant_config_loader = tenant_config_loader
        self.capability_router = capability_router
        self.tool_call_repository = tool_call_repository

    def execute(self, request: CreateMessageRequest) -> ProcessMessageResponse:
        tenant_context = self.tenant_config_loader.load(request.tenant_id)

        # 1. Создать Message (role = user, status = received, intent = null)
        new_message = Message(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            channel=request.channel,
            external_user_id=request.external_user_id,
            conversation_id=request.conversation_id,
            role=MessageRole.USER,
            content=request.content,
            intent=None,
            status=MessageStatus.RECEIVED,
            metadata=request.metadata,
            created_at=datetime.now(),
            processed_at=None,
        )

        # 2. Сохранить Message
        self.message_repository.save(new_message)

        # 3. Обновить status = processing (and save)
        new_message.status = MessageStatus.PROCESSING
        self.message_repository.save(new_message)

        # 4. Создать AgentInput из Message + request
        agent_input = AgentInput(
            tenant_id=new_message.tenant_id,
            conversation_id=new_message.conversation_id,
            message_id=new_message.id,
            message_text=new_message.content,
            channel=new_message.channel,
            metadata=new_message.metadata,
            tenant_context=tenant_context,
        )

        try:
            # 5. Вызвать agent_runtime.run(agent_input)
            agent_result = self.agent_runtime.run(agent_input)
            capability_results = []
            tool_calls = []
            for capability_request in agent_result.requested_capabilities:
                started_at = perf_counter()
                capability_result = self.capability_router.execute(tenant_context, capability_request)
                latency_ms = int((perf_counter() - started_at) * 1000)
                capability_results.append(capability_result)

                tool_call = ToolCall(
                    id=str(uuid.uuid4()),
                    tenant_id=new_message.tenant_id,
                    message_id=new_message.id,
                    conversation_id=new_message.conversation_id,
                    capability_name=capability_request.name,
                    provider=capability_result.provider,
                    input=capability_request.input,
                    output=capability_result.output,
                    status=capability_result.status,
                    error=capability_result.error,
                    latency_ms=latency_ms,
                    created_at=datetime.now(),
                )
                self.tool_call_repository.create(tool_call)
                tool_calls.append(tool_call)

            response_text = agent_result.response_text
            for capability_result in capability_results:
                if capability_result.user_message:
                    response_text = capability_result.user_message
                    break

            # 6. Обновить Message (intent = agent_result.intent, status = processed, processed_at = now)
            new_message.intent = agent_result.intent
            new_message.status = MessageStatus.PROCESSED
            new_message.processed_at = datetime.now()

            # 7. Сохранить/обновить Message
            self.message_repository.save(new_message)

            # 8. Вернуть ProcessMessageResponse
            content_response = MessageResponse(
                id=new_message.id,
                tenant_id=new_message.tenant_id,
                conversation_id=new_message.conversation_id,
                channel=new_message.channel,
                external_user_id=new_message.external_user_id,
                role=new_message.role,
                content=new_message.content,
                intent=new_message.intent,
                status=new_message.status,
                metadata=new_message.metadata,
                created_at=new_message.created_at,
                processed_at=new_message.processed_at,
            )

            return ProcessMessageResponse(
                message=content_response,
                intent=new_message.intent,
                response_text=response_text,
                requested_capabilities=agent_result.requested_capabilities,
                capability_results=capability_results,
                tool_calls=[self._to_tool_call_response(tool_call) for tool_call in tool_calls],
                status=new_message.status,
            )

        except Exception as e:
            # Если agent упал:
            # - status = failed
            # - processed_at = now
            # - сохранить ошибку в metadata или error field later
            # - вернуть ошибку или controlled response
            new_message.status = MessageStatus.FAILED
            new_message.processed_at = datetime.now()

            error_info = {"error": str(e)}
            if new_message.metadata:
                new_message.metadata = {**new_message.metadata, **error_info}
            else:
                new_message.metadata = error_info

            self.message_repository.save(new_message)

            content_response = MessageResponse(
                id=new_message.id,
                tenant_id=new_message.tenant_id,
                conversation_id=new_message.conversation_id,
                channel=new_message.channel,
                external_user_id=new_message.external_user_id,
                role=new_message.role,
                content=new_message.content,
                intent=new_message.intent,
                status=new_message.status,
                metadata=new_message.metadata,
                created_at=new_message.created_at,
                processed_at=new_message.processed_at,
            )

            return ProcessMessageResponse(
                message=content_response,
                intent=None,
                response_text="Failed to process the message due to an internal agent error.",
                requested_capabilities=None,
                capability_results=None,
                tool_calls=None,
                status=new_message.status,
            )

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
