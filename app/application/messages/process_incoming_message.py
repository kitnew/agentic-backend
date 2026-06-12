import uuid
from datetime import datetime

from app.agent.contracts.input import AgentInput
from app.agent.runtime import AgentRuntime
from app.application.capabilities.executor import BackendCapabilityExecutor
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityStatus
from app.domain.conversations.entities import Conversation
from app.domain.conversations.enums import ConversationStatus
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageRole, MessageStatus
from app.infrastructure.repositories.conversation_repository import ConversationRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.schemas.messages import CreateMessageRequest, MessageResponse, ProcessMessageResponse
from app.tenants.loader import TenantConfigLoader


class ConversationNotFoundError(Exception):
    pass


class ConversationTenantMismatchError(Exception):
    pass


class ProcessIncomingMessage:
    """Orchestrates incoming chat messages and lets the agent graph execute capabilities."""

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
        chat_history = self._build_chat_history(conversation.id)

        user_message = Message(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            channel=request.channel,
            external_user_id=request.external_user_id,
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=request.content,
            status=MessageStatus.RECEIVED,
            metadata=request.metadata,
            created_at=datetime.now(),
            processed_at=None,
        )
        self.message_repository.save(user_message)

        user_message.status = MessageStatus.PROCESSING
        self.message_repository.save(user_message)

        agent_input = AgentInput(
            tenant_id=user_message.tenant_id,
            conversation_id=user_message.conversation_id,
            message_id=user_message.id,
            message_text=user_message.content,
            channel=user_message.channel,
            tenant_context=tenant_context
        )
        capability_executor = BackendCapabilityExecutor(
            tenant_context=tenant_context,
            message=user_message,
            capability_router=self.capability_router,
            tool_call_repository=self.tool_call_repository,
        )

        try:
            agent_result = self.agent_runtime.run(agent_input, capability_executor=capability_executor)
            capability_results = agent_result.capability_results
            tool_calls = agent_result.tool_calls
            response_text = agent_result.response_text or ""
            has_capability_failure = any(
                capability_result.status == CapabilityStatus.FAILED
                for capability_result in capability_results
            )
            final_message_status = (
                MessageStatus.FAILED if has_capability_failure else MessageStatus.PROCESSED
            )

            user_message.status = final_message_status
            user_message.processed_at = datetime.now()
            self.message_repository.save(user_message)

            assistant_message = Message(
                id=str(uuid.uuid4()),
                tenant_id=user_message.tenant_id,
                conversation_id=conversation.id,
                channel=user_message.channel,
                external_user_id=user_message.external_user_id,
                role=MessageRole.ASSISTANT,
                content=response_text,
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

            return ProcessMessageResponse(
                conversation_id=conversation.id,
                user_message=self._to_message_response(user_message),
                assistant_message=self._to_message_response(assistant_message),
                response_text=response_text,
                requested_capabilities=agent_result.requested_capabilities,
                capability_results=capability_results,
                tool_calls=tool_calls,
                agent_trace=agent_result.trace,
                status=user_message.status,
            )

        except Exception as exc:
            user_message.status = MessageStatus.FAILED
            user_message.processed_at = datetime.now()
            user_message.metadata = {**(user_message.metadata or {}), "error": str(exc)}
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
                status=MessageStatus.FAILED,
                metadata={"error": str(exc)},
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
                response_text=failure_text,
                requested_capabilities=[],
                capability_results=[],
                tool_calls=[],
                agent_trace=None,
                status=user_message.status,
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
            status=message.status,
            metadata=message.metadata,
            created_at=message.created_at,
            processed_at=message.processed_at,
        )

    def _build_chat_history(
        self,
        conversation_id: str,
        limit: int = 20,
    ) -> list[dict]:
        messages = self.message_repository.list_by_conversation_id(conversation_id)
        recent_messages = messages[-limit:]
        return [
            {
                "role": message.role.value,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            }
            for message in recent_messages
        ]

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

        if request.external_user_id:
            conversation = self.conversation_repository.get_active_by_participant(
                tenant_id=request.tenant_id,
                channel=request.channel,
                external_user_id=request.external_user_id,
            )
            if conversation:
                conversation.updated_at = datetime.now()
                return self.conversation_repository.update(conversation)

        now = datetime.now()
        conversation = Conversation(
            id=str(uuid.uuid4()),
            tenant_id=request.tenant_id,
            channel=request.channel,
            external_user_id=request.external_user_id,
            status=ConversationStatus.ACTIVE,
            metadata=None,
            created_at=now,
            updated_at=now,
        )
        return self.conversation_repository.create(conversation)
