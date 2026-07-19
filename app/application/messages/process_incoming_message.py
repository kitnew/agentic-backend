import uuid
from datetime import datetime

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, message_to_dict

from app.agent.runtime import AgentRuntime
from app.agent.schemas.context import AgentContext
from app.agent.schemas.input import AgentInput
from app.agent.tools import create_agent_tools, create_langchain_tools
from app.application.capabilities.boundary import CapabilityExecutor
from app.application.capabilities.executor import BackendCapabilityExecutor, CapabilityExecution
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityStatus
from app.core.timing import (
    finish_timing_trace,
    new_timing_trace,
    record_component_timing,
    start_timer,
)
from app.domain.conversations.entities import Conversation
from app.domain.conversations.enums import ConversationStatus
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageRole, MessageStatus
from app.infrastructure.repositories.conversation_repository import ConversationRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.schemas.messages import CreateMessageRequest, MessageResponse, ProcessMessageResponse
from app.tenants.loader import TenantConfigLoader
from app.tenants.policies import (
    Clock,
    localized_phrase_match,
    localized_response,
    reservation_cutoff_reached,
    tenant_local_datetime,
    utc_now,
)
from app.tenants.schemas import TenantContext


class ConversationNotFoundError(Exception):
    pass


class ConversationTenantMismatchError(Exception):
    pass


def resolve_conversation(
    repository: ConversationRepository,
    *,
    tenant_id: str,
    channel: str,
    conversation_id: str | None = None,
    external_user_id: str | None = None,
) -> Conversation:
    if conversation_id:
        conversation = repository.get_by_id(conversation_id)
        if not conversation:
            raise ConversationNotFoundError(f"Conversation not found: {conversation_id}")
        if conversation.tenant_id != tenant_id:
            raise ConversationTenantMismatchError(
                f"Conversation {conversation_id} does not belong to tenant {tenant_id}"
            )
        conversation.updated_at = datetime.now()
        return repository.update(conversation)

    if external_user_id:
        conversation = repository.get_active_by_participant(
            tenant_id=tenant_id,
            channel=channel,
            external_user_id=external_user_id,
        )
        if conversation:
            conversation.updated_at = datetime.now()
            return repository.update(conversation)

    now = datetime.now()
    return repository.create(
        Conversation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            channel=channel,
            external_user_id=external_user_id,
            status=ConversationStatus.ACTIVE,
            metadata=None,
            created_at=now,
            updated_at=now,
        )
    )


class ProcessIncomingMessage:
    """Stores an incoming message and runs the prototype LangGraph agent flow."""

    def __init__(
        self,
        message_repository: MessageRepository,
        agent_runtime: AgentRuntime,
        tenant_config_loader: TenantConfigLoader,
        capability_router: CapabilityRouter,
        tool_call_repository: ToolCallRepository,
        conversation_repository: ConversationRepository,
        capability_executor: CapabilityExecutor | None = None,
        clock: Clock = utc_now,
    ):
        self.message_repository = message_repository
        self.agent_runtime = agent_runtime
        self.tenant_config_loader = tenant_config_loader
        self.capability_router = capability_router
        self.tool_call_repository = tool_call_repository
        self.conversation_repository = conversation_repository
        self.capability_executor = capability_executor
        self.clock = clock

    def execute(self, request: CreateMessageRequest, *, text_callback=None) -> ProcessMessageResponse:
        total_timer = start_timer()
        pipeline_timings = new_timing_trace()
        component_timer = start_timer()
        tenant_context = self.tenant_config_loader.load(request.tenant_id)
        tenant_now = tenant_local_datetime(tenant_context, self.clock)
        record_component_timing(pipeline_timings, "tenant_config_load", component_timer)
        component_timer = start_timer()
        conversation = self._get_or_create_conversation(request)
        record_component_timing(
            pipeline_timings,
            "conversation_get_or_create",
            component_timer,
            conversation_id=conversation.id,
        )
        component_timer = start_timer()
        chat_history = self._build_chat_history(conversation.id)
        record_component_timing(
            pipeline_timings,
            "chat_history_load",
            component_timer,
            message_count=len(chat_history),
        )

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
        component_timer = start_timer()
        self.message_repository.save(user_message)
        record_component_timing(
            pipeline_timings,
            "user_message_save",
            component_timer,
            message_id=user_message.id,
        )

        try:
            agent_input = AgentInput(
                message_text=user_message.content,
                chat_history=chat_history,
            )
            component_timer = start_timer()
            context = self._build_agent_context(
                tenant_context,
                conversation.id,
                metadata=request.metadata,
                local_now=tenant_now,
            )
            fixed_response = self._policy_response(
                tenant_context,
                user_message.content,
                request.metadata,
                tenant_now,
            )
            if fixed_response:
                agent_tools = []
                if text_callback is not None:
                    text_callback(fixed_response)
                agent_output = {
                    "response_text": fixed_response,
                    "response": message_to_dict(AIMessage(content=fixed_response)),
                    "agent_trace": {"policy_response": True, "context": context},
                }
            else:
                capability_executor = BackendCapabilityExecutor(
                    tenant_context=tenant_context,
                    message=user_message,
                    capability_router=self.capability_router,
                    tool_call_repository=self.tool_call_repository,
                    capability_executor=self.capability_executor,
                )
                agent_tools = create_agent_tools(
                    capability_executor=capability_executor,
                    raw_message=user_message.content,
                    tenant_context=tenant_context,
                )
                run_kwargs = {
                    "context": context,
                    "tools": create_langchain_tools(agent_tools),
                }
                if text_callback is not None:
                    run_kwargs["text_callback"] = text_callback
                agent_output = self.agent_runtime.run(agent_input, **run_kwargs)
            record_component_timing(pipeline_timings, "agent_runtime", component_timer)
            component_timer = start_timer()
            capability_executions = self._collect_capability_executions(agent_tools)
            capability_results = [execution.result for execution in capability_executions]
            tool_calls = [
                execution.tool_call
                for execution in capability_executions
                if execution.tool_call is not None
            ]
            record_component_timing(
                pipeline_timings,
                "capability_collection",
                component_timer,
                capability_execution_count=len(capability_executions),
                tool_call_count=len(tool_calls),
            )
            response_text = agent_output["response_text"] or self._fallback_capability_message(
                capability_executions
            )
            has_capability_failure = any(
                capability_result.status == CapabilityStatus.FAILED
                for capability_result in capability_results
            )
            final_message_status = (
                MessageStatus.FAILED if has_capability_failure else MessageStatus.PROCESSED
            )

            component_timer = start_timer()
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
                metadata={"agent_response": agent_output["response"]},
                created_at=datetime.now(),
                processed_at=datetime.now(),
            )
            self.message_repository.save(assistant_message)

            if has_capability_failure:
                conversation.status = ConversationStatus.FAILED
            conversation.updated_at = datetime.now()
            self.conversation_repository.update(conversation)
            record_component_timing(pipeline_timings, "message_persistence", component_timer)
            agent_trace = dict(agent_output["agent_trace"] or {})
            agent_trace["message_pipeline_timings"] = finish_timing_trace(
                pipeline_timings,
                total_timer,
            )

            return ProcessMessageResponse(
                conversation_id=conversation.id,
                user_message=self._to_message_response(user_message),
                assistant_message=self._to_message_response(assistant_message),
                response_text=response_text,
                requested_capabilities=[
                    execution.request for execution in capability_executions
                ],
                capability_results=capability_results,
                tool_calls=tool_calls,
                agent_trace=agent_trace,
                status=user_message.status,
            )

        except Exception as exc:
            component_timer = start_timer()
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
            record_component_timing(pipeline_timings, "failure_persistence", component_timer)
            agent_trace = {
                "error": str(exc),
                "type": exc.__class__.__name__,
                "message_pipeline_timings": finish_timing_trace(
                    pipeline_timings,
                    total_timer,
                ),
            }

            return ProcessMessageResponse(
                conversation_id=conversation.id,
                user_message=self._to_message_response(user_message),
                assistant_message=self._to_message_response(assistant_message),
                response_text=failure_text,
                requested_capabilities=[],
                capability_results=[],
                tool_calls=[],
                agent_trace=agent_trace,
                status=user_message.status,
            )

    def _collect_capability_executions(self, agent_tools) -> list[CapabilityExecution]:
        executions: list[CapabilityExecution] = []
        for tool in agent_tools:
            executions.extend(getattr(tool, "executions", []))
        return executions

    def _fallback_capability_message(
        self,
        capability_executions: list[CapabilityExecution],
    ) -> str:
        for execution in reversed(capability_executions):
            if execution.result.user_message:
                return execution.result.user_message
        return ""

    def _build_agent_context(
        self,
        tenant_context: TenantContext,
        conversation_id: str,
        *,
        metadata: dict | None = None,
        local_now: datetime | None = None,
    ) -> AgentContext:
        tenant_now = local_now or tenant_local_datetime(tenant_context, self.clock)

        context: AgentContext = {
            "tenant_id": tenant_context.tenant_id,
            "conversation_id": conversation_id,
            "agent_profile": tenant_context.agent.profile,
            "now": tenant_now.isoformat(),
            "datetime": tenant_now.isoformat(),
            "current_local_datetime": tenant_now.isoformat(),
            "current_local_date": tenant_now.date().isoformat(),
            "current_local_time": tenant_now.time().isoformat(timespec="seconds"),
            "locale": tenant_context.locale or tenant_context.default_language,
            "date": tenant_now.date().isoformat(),
            "time": tenant_now.time().isoformat(timespec="seconds"),
            "timezone": tenant_context.timezone,
            "agent_style_rules": tenant_context.agent.style_rules,
            "tenant_instructions": "\n\n".join(
                part
                for part in (
                    tenant_context.prompt.tenant_instructions,
                    tenant_context.prompt.instructions,
                )
                if part
            ),
            "tenant_identity": {
                "tenant_id": tenant_context.tenant_id,
                "display_name": tenant_context.name,
                "business_type": tenant_context.business_type,
                "assistant_name": tenant_context.agent.display_name,
                "assistant_role": tenant_context.agent.role,
                "default_locale": tenant_context.default_locale,
                "supported_locales": tenant_context.supported_locales,
                "default_greeting": tenant_context.agent.greeting_phrase,
                "localized_greetings": tenant_context.agent.localized_greetings,
            },
            "business_info": self._build_prompt_business_info(tenant_context),
            "reservation_policy": self._build_reservation_policy(tenant_context),
            "required_reservation_fields": self._build_required_reservation_fields(tenant_context),
            "schedule_summary": self._build_schedule_summary(tenant_context),
            "supported_operations": self._build_supported_operations(tenant_context),
            "conversation_scope": self._build_conversation_scope(tenant_context),
            "knowledge_base": tenant_context.prompt.knowledge_base,
            "supplementary_guidance": tenant_context.prompt.supplementary_guidance,
        }
        metadata = metadata or {}
        for key in ("call_session_id", "channel", "language", "thread_id", "idempotency_key"):
            if metadata.get(key):
                context[key] = metadata[key]
        return context

    def _policy_response(
        self,
        tenant_context: TenantContext,
        message: str,
        metadata: dict | None,
        local_now: datetime,
    ) -> str | None:
        preferred_locale = (metadata or {}).get("language")
        scope = tenant_context.conversation_scope
        if scope.mode == "property_only":
            locale = localized_phrase_match(
                message,
                scope.blocked_phrases,
                preferred_locale,
            )
            if locale:
                return localized_response(
                    scope.localized_refusals,
                    locale,
                    tenant_context.default_locale,
                )

        reservation = tenant_context.reservation
        if reservation_cutoff_reached(tenant_context, local_now):
            locale = localized_phrase_match(
                message,
                reservation.new_request_phrases,
                preferred_locale,
            )
            if locale:
                return localized_response(
                    reservation.cutoff_responses,
                    locale,
                    tenant_context.default_locale,
                )
        return None

    def _build_conversation_scope(self, tenant_context: TenantContext) -> str:
        scope = tenant_context.conversation_scope
        if scope.mode != "property_only":
            return ""
        refusals = "\n".join(
            f"- {locale}: {response}"
            for locale, response in scope.localized_refusals.items()
        )
        return (
            f"Only answer questions related to {tenant_context.name}, its accommodation, "
            "services, relevant nearby places covered by the knowledge base, and current "
            "guest or property emergencies. Refuse unrelated requests without answering them.\n"
            f"Use the matching fixed refusal:\n{refusals}"
        )

    def _build_prompt_business_info(self, tenant_context: TenantContext) -> dict:
        return tenant_context.business_info.model_dump(mode="json", exclude_none=True)

    def _build_supported_operations(self, tenant_context: TenantContext) -> str:
        labels = {
            "factual_qa": "Factual property questions",
            "room_recommendation": "Room recommendations",
            "availability_check": "Room availability checks",
            "reservation_create": "New reservation submission",
            "reservation_modify": "Reservation modification",
            "reservation_cancel": "Reservation cancellation",
            "reservation_lookup": "Reservation lookup",
            "human_transfer": "Human call transfer",
        }
        return "\n".join(
            f"- {labels[name]}: {'supported' if enabled else 'not supported'}"
            for name, enabled in tenant_context.features.model_dump().items()
        )

    def _build_reservation_policy(self, tenant_context: TenantContext) -> str:
        reservation = tenant_context.reservation
        policy_parts = [
            "New reservation submission is currently supported."
            if reservation.enabled
            else "New reservation submission is currently not supported."
        ]
        if reservation.request_cutoff_local_time:
            cutoff = reservation.request_cutoff_local_time.isoformat(timespec="minutes")
            policy_parts.append(
                f"Do not accept or submit a new reservation request at or after {cutoff} "
                "in the tenant's local timezone. Availability and factual questions remain allowed."
            )
        if reservation.enabled and (
            reservation.mode == "request_only" or not reservation.can_confirm_reservation
        ):
            policy_parts.append(
                "Reservation handling is request-only. Describe reservations as submitted "
                "requests waiting for staff confirmation. "
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
        return resolve_conversation(
            self.conversation_repository,
            tenant_id=request.tenant_id,
            channel=request.channel,
            conversation_id=request.conversation_id,
            external_user_id=request.external_user_id,
        )
