import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agent.runtime import AgentRuntime
from app.agent.schemas.context import AgentContext
from app.agent.schemas.input import AgentInput
from app.domain.conversations.entities import Conversation
from app.domain.conversations.enums import ConversationStatus
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageRole, MessageStatus
from app.infrastructure.repositories.conversation_repository import ConversationRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.schemas.messages import CreateMessageRequest, MessageResponse, ProcessMessageResponse
from app.tenants.loader import TenantConfigLoader
from app.tenants.schemas import TenantContext


class ConversationNotFoundError(Exception):
    pass


class ConversationTenantMismatchError(Exception):
    pass


class ProcessIncomingMessage:
    """Stores an incoming message and runs the prototype LangGraph agent flow."""

    def __init__(
        self,
        message_repository: MessageRepository,
        agent_runtime: AgentRuntime,
        tenant_config_loader: TenantConfigLoader,
        conversation_repository: ConversationRepository,
    ):
        self.message_repository = message_repository
        self.agent_runtime = agent_runtime
        self.tenant_config_loader = tenant_config_loader
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
            status=MessageStatus.PROCESSING,
            metadata=request.metadata,
            created_at=datetime.now(),
            processed_at=None,
        )
        self.message_repository.save(user_message)

        try:
            agent_input = AgentInput(
                message_text=user_message.content,
                chat_history=chat_history,
            )
            agent_output = self.agent_runtime.run(
                agent_input,
                context=self._build_agent_context(tenant_context, conversation.id),
            )
            response_text = agent_output["response_text"]

            user_message.status = MessageStatus.PROCESSED
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
                status=MessageStatus.PROCESSED,
                metadata={"agent_response": agent_output["response"]},
                created_at=datetime.now(),
                processed_at=datetime.now(),
            )
            self.message_repository.save(assistant_message)

            conversation.updated_at = datetime.now()
            self.conversation_repository.update(conversation)

            return ProcessMessageResponse(
                conversation_id=conversation.id,
                user_message=self._to_message_response(user_message),
                assistant_message=self._to_message_response(assistant_message),
                response_text=response_text,
                requested_capabilities=[],
                capability_results=[],
                tool_calls=[],
                agent_trace=agent_output["agent_trace"],
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
                agent_trace={"error": str(exc), "type": exc.__class__.__name__},
                status=user_message.status,
            )

    def _build_agent_context(
        self,
        tenant_context: TenantContext,
        conversation_id: str,
    ) -> AgentContext:
        enabled_capabilities = [
            name
            for name, capability in tenant_context.capabilities.items()
            if capability.enabled
        ]
        tenant_now = datetime.now(ZoneInfo(tenant_context.timezone))

        return {
            "tenant_id": tenant_context.tenant_id,
            "conversation_id": conversation_id,
            "agent_profile": tenant_context.agent.profile,
            "now": tenant_now.isoformat(),
            "datetime": tenant_now.isoformat(),
            "locale": tenant_context.locale or tenant_context.default_language,
            "date": tenant_now.date().isoformat(),
            "time": tenant_now.time().isoformat(timespec="seconds"),
            "timezone": tenant_context.timezone,
            "agent_style_rules": tenant_context.agent.style_rules,
            "tenant_instructions": tenant_context.prompt.tenant_instructions,
            "business_info": self._build_prompt_business_info(tenant_context),
            "reservation_policy": self._build_reservation_policy(tenant_context),
            "required_reservation_fields": self._build_required_reservation_fields(tenant_context),
            "schedule_summary": self._build_schedule_summary(tenant_context),
            "enabled_capabilities": enabled_capabilities,
        }

    def _build_prompt_business_info(self, tenant_context: TenantContext) -> dict[str, str]:
        raw_info = tenant_context.business_info.model_dump(exclude_none=True)
        return {key: str(value) for key, value in raw_info.items()}

    def _build_reservation_policy(self, tenant_context: TenantContext) -> str:
        reservation = tenant_context.reservation
        policy_parts = [
            f"enabled: {reservation.enabled}",
            f"mode: {reservation.mode}",
            f"requires_human_confirmation: {reservation.requires_human_confirmation}",
            f"can_confirm_reservation: {reservation.can_confirm_reservation}",
        ]
        if reservation.mode == "request_only" or not reservation.can_confirm_reservation:
            policy_parts.append(
                "Describe reservations as submitted requests waiting for staff confirmation. "
                "Do not describe them as confirmed reservations."
            )
        return "\n".join(policy_parts)

    def _build_required_reservation_fields(self, tenant_context: TenantContext) -> list[str]:
        fields = []
        for field_name, field_config in tenant_context.reservation.required_fields.items():
            if field_config.required:
                fields.append(f"{field_name}: {field_config.label}")
        return fields

    def _build_schedule_summary(self, tenant_context: TenantContext) -> str:
        day_order = [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
        weekly_schedule = tenant_context.reservation.schedule.weekly
        summaries = []

        for day in day_order:
            day_config = weekly_schedule.get(day)
            if not day_config:
                continue
            if not day_config.open:
                summaries.append(f"{day}: closed")
                continue

            intervals = ", ".join(
                f"{interval.start}-{interval.end}" for interval in day_config.intervals
            )
            summaries.append(f"{day}: {intervals or 'open'}")

        return "\n".join(summaries)

    def _build_chat_history(
        self,
        conversation_id: str,
        limit: int = 20,
    ) -> list[BaseMessage]:
        messages = self.message_repository.list_by_conversation_id(conversation_id)
        recent_messages = messages[-limit:]
        chat_history: list[BaseMessage] = []

        for message in recent_messages:
            if message.role == MessageRole.USER:
                chat_history.append(HumanMessage(content=message.content))
            elif message.role == MessageRole.ASSISTANT:
                chat_history.append(AIMessage(content=message.content))

        return chat_history

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
