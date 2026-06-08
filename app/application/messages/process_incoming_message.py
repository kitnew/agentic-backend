import uuid
from datetime import datetime
from time import perf_counter

from app.infrastructure.repositories.message_repository import MessageRepository
from app.agent.runtime import AgentRuntime
from app.agent.schemas import AgentInput
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityRequest, CapabilityStatus
from app.domain.conversations.entities import Conversation
from app.domain.conversations.enums import ConversationStatus
from app.domain.tool_calls.entities import ToolCall
from app.domain.tool_calls.enums import ToolCallStatus
from app.infrastructure.repositories.conversation_repository import ConversationRepository
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.schemas.messages import CreateMessageRequest, MessageResponse, ProcessMessageResponse
from app.schemas.tool_calls import ToolCallResponse
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageStatus, MessageRole
from app.tenants.loader import TenantConfigLoader


class ConversationNotFoundError(Exception):
    pass


class ConversationTenantMismatchError(Exception):
    pass


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
        conversation_repository: ConversationRepository,
    ):
        self.message_repository = message_repository
        self.agent_runtime = agent_runtime
        self.tenant_config_loader = tenant_config_loader
        self.capability_router = capability_router
        self.tool_call_repository = tool_call_repository
        self.conversation_repository = conversation_repository

    def execute(self, request: CreateMessageRequest) -> ProcessMessageResponse:
        tenant_context = self.tenant_config_loader.load(request.tenant_id)
        conversation = self._get_or_create_conversation(request)

        # 1. Создать Message (role = user, status = received, intent = null)
        user_message = Message(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            channel=request.channel,
            external_user_id=request.external_user_id,
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=request.content,
            intent=None,
            status=MessageStatus.RECEIVED,
            metadata=request.metadata,
            created_at=datetime.now(),
            processed_at=None,
        )

        # 2. Сохранить Message
        self.message_repository.save(user_message)

        # 3. Обновить status = processing (and save)
        user_message.status = MessageStatus.PROCESSING
        self.message_repository.save(user_message)

        # 4. Создать AgentInput из Message + request
        agent_input = AgentInput(
            tenant_id=user_message.tenant_id,
            conversation_id=user_message.conversation_id,
            message_id=user_message.id,
            message_text=user_message.content,
            channel=user_message.channel,
            metadata=user_message.metadata,
            tenant_context=tenant_context,
        )

        try:
            # 5. Вызвать agent_runtime.run(agent_input)
            agent_result = self.agent_runtime.run(agent_input)
            capability_results = []
            tool_calls = []
            for capability_request in agent_result.requested_capabilities:
                execution_request = self._with_execution_context(capability_request, user_message)
                started_at = perf_counter()
                capability_result = self.capability_router.execute(tenant_context, execution_request)
                latency_ms = int((perf_counter() - started_at) * 1000)
                capability_results.append(capability_result)

                tool_call = ToolCall(
                    id=str(uuid.uuid4()),
                    tenant_id=user_message.tenant_id,
                    message_id=user_message.id,
                    conversation_id=user_message.conversation_id,
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
                tool_calls.append(tool_call)

            response_text = agent_result.response_text
            for capability_result in capability_results:
                if capability_result.user_message:
                    response_text = capability_result.user_message
                    break
            has_capability_failure = any(
                capability_result.status == CapabilityStatus.FAILED
                for capability_result in capability_results
            )
            final_message_status = (
                MessageStatus.FAILED
                if has_capability_failure
                else MessageStatus.PROCESSED
            )

            # 6. Обновить Message (intent = agent_result.intent, status = processed, processed_at = now)
            user_message.intent = agent_result.intent
            user_message.status = final_message_status
            user_message.processed_at = datetime.now()

            # 7. Сохранить/обновить Message
            self.message_repository.save(user_message)

            assistant_message = Message(
                id=str(uuid.uuid4()),
                tenant_id=user_message.tenant_id,
                conversation_id=conversation.id,
                channel=user_message.channel,
                external_user_id=user_message.external_user_id,
                role=MessageRole.ASSISTANT,
                content=response_text,
                intent=agent_result.intent,
                status=final_message_status,
                metadata=None,
                created_at=datetime.now(),
                processed_at=datetime.now(),
            )
            self.message_repository.save(assistant_message)
            if has_capability_failure:
                conversation.status = ConversationStatus.FAILED
            conversation.updated_at = datetime.now()
            self.conversation_repository.update(conversation)

            # 8. Вернуть ProcessMessageResponse
            return ProcessMessageResponse(
                conversation_id=conversation.id,
                user_message=self._to_message_response(user_message),
                assistant_message=self._to_message_response(assistant_message),
                intent=user_message.intent,
                response_text=response_text,
                requested_capabilities=agent_result.requested_capabilities,
                capability_results=capability_results,
                tool_calls=[self._to_tool_call_response(tool_call) for tool_call in tool_calls],
                status=user_message.status,
            )

        except Exception as e:
            # Если agent упал:
            # - status = failed
            # - processed_at = now
            # - сохранить ошибку в metadata или error field later
            # - вернуть ошибку или controlled response
            user_message.status = MessageStatus.FAILED
            user_message.processed_at = datetime.now()

            error_info = {"error": str(e)}
            if user_message.metadata:
                user_message.metadata = {**user_message.metadata, **error_info}
            else:
                user_message.metadata = error_info

            self.message_repository.save(user_message)

            failure_text = "Failed to process the message due to an internal agent error."
            assistant_message = Message(
                id=str(uuid.uuid4()),
                tenant_id=user_message.tenant_id,
                conversation_id=conversation.id,
                channel=user_message.channel,
                external_user_id=user_message.external_user_id,
                role=MessageRole.ASSISTANT,
                content=failure_text,
                intent=None,
                status=MessageStatus.FAILED,
                metadata=error_info,
                created_at=datetime.now(),
                processed_at=datetime.now(),
            )
            self.message_repository.save(assistant_message)
            conversation.status = ConversationStatus.FAILED
            conversation.updated_at = datetime.now()
            self.conversation_repository.update(conversation)

            return ProcessMessageResponse(
                conversation_id=conversation.id,
                user_message=self._to_message_response(user_message),
                assistant_message=self._to_message_response(assistant_message),
                intent=None,
                response_text=failure_text,
                requested_capabilities=None,
                capability_results=None,
                tool_calls=None,
                status=user_message.status,
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

    def _to_message_response(self, message: Message) -> MessageResponse:
        return MessageResponse(
            id=message.id,
            tenant_id=message.tenant_id,
            conversation_id=message.conversation_id,
            channel=message.channel,
            external_user_id=message.external_user_id,
            role=message.role,
            content=message.content,
            intent=message.intent,
            status=message.status,
            metadata=message.metadata,
            created_at=message.created_at,
            processed_at=message.processed_at,
        )

    def _with_execution_context(
        self,
        capability_request: CapabilityRequest,
        message: Message,
    ) -> CapabilityRequest:
        execution_input = {
            **capability_request.input,
            "tenant_id": message.tenant_id,
            "message_id": message.id,
            "conversation_id": message.conversation_id,
            "source_channel": message.channel,
        }
        return capability_request.model_copy(update={"input": execution_input})

    def _get_or_create_conversation(self, request: CreateMessageRequest) -> Conversation:
        if request.conversation_id:
            conversation = self.conversation_repository.get_by_id(request.conversation_id)
            if not conversation:
                raise ConversationNotFoundError(f"Conversation not found: {request.conversation_id}")

            if conversation.tenant_id != request.tenant_id:
                raise ConversationTenantMismatchError(
                    f"Conversation {request.conversation_id} does not belong to tenant {request.tenant_id}"
                )

            conversation.updated_at = datetime.now()
            return self.conversation_repository.update(conversation)

        now = datetime.now()
        conversation = Conversation(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            channel=request.channel,
            external_user_id=request.external_user_id,
            status=ConversationStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        return self.conversation_repository.create(conversation)
