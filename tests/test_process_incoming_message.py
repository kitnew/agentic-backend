from app.agent.contracts.output import AgentResult
from app.agent.contracts.state import (
    AgentDecision,
    ChatMemoryExtraction,
    ReservationExtractionResult,
    ResponseDraft,
    ResponseValidationResult,
    TaskStateValidationResult,
)
from app.agent.runtime import AgentRuntime
from app.api.routes.conversations import list_conversation_messages
from app.application.messages.process_incoming_message import ProcessIncomingMessage
from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus
from app.domain.conversations.entities import Conversation
from app.domain.conversations.enums import ConversationStatus
from app.domain.messages.entities import Message
from app.domain.tool_calls.entities import ToolCall
from app.schemas.messages import CreateMessageRequest
from app.tenants.loader import TenantConfigLoader, TenantConfigNotFoundError


class InMemoryConversationRepository:
    def __init__(self):
        self.conversations = {}

    def create(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation.model_copy()
        return conversation

    def get_by_id(self, conversation_id: str) -> Conversation | None:
        conversation = self.conversations.get(conversation_id)
        return conversation.model_copy() if conversation else None

    def get_active_by_participant(
        self,
        *,
        tenant_id: str,
        channel: str,
        external_user_id: str,
    ) -> Conversation | None:
        conversations = [
            conversation
            for conversation in self.conversations.values()
            if conversation.tenant_id == tenant_id
            and conversation.channel == channel
            and conversation.external_user_id == external_user_id
            and conversation.status == ConversationStatus.ACTIVE
        ]
        if not conversations:
            return None
        return sorted(conversations, key=lambda item: item.updated_at)[-1].model_copy()

    def update(self, conversation: Conversation) -> Conversation:
        self.conversations[conversation.id] = conversation.model_copy()
        return conversation


class InMemoryMessageRepository:
    def __init__(self):
        self.messages = {}

    def save(self, message: Message) -> Message:
        self.messages[message.id] = message.model_copy()
        return message

    def get_by_id(self, message_id: str) -> Message | None:
        message = self.messages.get(message_id)
        return message.model_copy() if message else None

    def list_by_conversation_id(self, conversation_id: str) -> list[Message]:
        messages = [
            message.model_copy()
            for message in self.messages.values()
            if message.conversation_id == conversation_id
        ]
        return sorted(messages, key=lambda message: message.created_at)


class InMemoryToolCallRepository:
    def __init__(self):
        self.tool_calls = []

    def create(self, tool_call: ToolCall) -> ToolCall:
        self.tool_calls.append(tool_call.model_copy())
        return tool_call

    def list_by_message_id(self, message_id: str) -> list[ToolCall]:
        return [
            tool_call.model_copy()
            for tool_call in self.tool_calls
            if tool_call.message_id == message_id
        ]


class FakeAgentRuntime:
    def __init__(self, response_text: str = ""):
        self.response_text = response_text
        self.inputs = []

    def run(self, agent_input, capability_executor=None):
        self.inputs.append(agent_input)
        request = CapabilityRequest(
            name="reservation.create_request",
            input={"raw_message": agent_input.message_text},
        )
        if capability_executor is None:
            return AgentResult(
                response_text=self.response_text,
                requested_capabilities=[request],
            )

        execution = capability_executor.execute(request)
        return AgentResult(
            response_text=execution.result.user_message or self.response_text,
            requested_capabilities=[execution.request],
            capability_results=[execution.result],
            tool_calls=[execution.tool_call] if execution.tool_call else [],
        )


class FakeCapabilityRouter:
    def __init__(self, status=CapabilityStatus.SUCCESS):
        self.status = status

    def execute(self, tenant_context, capability_request):
        return CapabilityResult(
            name=capability_request.name,
            status=self.status,
            provider="google_sheets",
            output={"row_appended": self.status == CapabilityStatus.SUCCESS},
            user_message="Vašu žiadosť o rezerváciu sme prijali. Personál ju potvrdí.",
            error="provider failed" if self.status == CapabilityStatus.FAILED else None,
        )


class FakeOpeningHoursAgentRuntime:
    def __init__(self):
        self.inputs = []

    def run(self, agent_input, capability_executor=None):
        self.inputs.append(agent_input)
        return AgentResult(
            response_text="Máme otvorené: 10:00 - 21:00 every day except Sunday",
            requested_capabilities=[],
            response_mode="direct",
        )


class FakeStructuredStateLlm:
    def __init__(self, outputs: list, schema):
        self.outputs = outputs
        self.schema = schema

    def invoke(self, messages):
        if self.outputs:
            return self.outputs.pop(0)
        return self.schema()


class FakeStateLlm:
    def __init__(self, outputs: list):
        self.outputs = outputs

    def with_structured_output(self, schema, method):
        return FakeStructuredStateLlm(self.outputs, schema)


def ok_response_validation() -> ResponseValidationResult:
    return ResponseValidationResult(
        ok=True,
        needs_revision=False,
        mentions_validation_errors=True,
        asks_for_missing_fields=True,
    )


def reservation_decision() -> AgentDecision:
    return AgentDecision(
        primary_intent="reservation_request",
        detected_intents=["reservation_request"],
        active_task="reservation_request",
    )


def build_use_case(capability_status=CapabilityStatus.SUCCESS, agent_response_text: str = ""):
    conversation_repository = InMemoryConversationRepository()
    message_repository = InMemoryMessageRepository()
    tool_call_repository = InMemoryToolCallRepository()
    use_case = ProcessIncomingMessage(
        message_repository=message_repository,
        agent_runtime=FakeAgentRuntime(agent_response_text),
        tenant_config_loader=TenantConfigLoader(),
        capability_router=FakeCapabilityRouter(capability_status),
        tool_call_repository=tool_call_repository,
        conversation_repository=conversation_repository,
    )
    return use_case, conversation_repository, message_repository, tool_call_repository


def test_stateful_reservation_uses_chat_history_not_conversation_metadata():
    conversation_repository = InMemoryConversationRepository()
    message_repository = InMemoryMessageRepository()
    tool_call_repository = InMemoryToolCallRepository()
    use_case = ProcessIncomingMessage(
        message_repository=message_repository,
        agent_runtime=AgentRuntime(
            FakeStateLlm(
                [
                    ChatMemoryExtraction(
                        current_question_intents=["parking_question"],
                        active_task="reservation_request",
                        task_status="collecting_info",
                        reservation_frame={
                            "guest_name": "Patrik",
                            "date": "zajtra",
                            "time": "19:00",
                            "party_size": 2,
                        },
                        current_reservation_fields={
                            "guest_name": "Patrik",
                            "date": "zajtra",
                            "time": "19:00",
                            "party_size": 2,
                        },
                        missing_fields=["phone"],
                    ),
                    AgentDecision(
                        primary_intent="reservation_request",
                        detected_intents=["parking_question", "reservation_request"],
                        active_task="reservation_request",
                    ),
                    ReservationExtractionResult(
                        field_updates={
                            "guest_name": "Patrik",
                            "date": "zajtra",
                            "time": "19:00",
                            "party_size": 2,
                        },
                        active_task="reservation_request",
                        task_status="collecting_info",
                    ),
                    TaskStateValidationResult(
                        task_status="collecting_info",
                        missing_fields=["phone"],
                    ),
                    ResponseDraft(
                        response_text=(
                            "Parkovanie je dostupné pri reštaurácii. "
                            "Pre dokončenie rezervácie mi prosím pošlite ešte telefónne číslo."
                        ),
                    ),
                    ok_response_validation(),
                    ChatMemoryExtraction(
                        answered_questions=["parking_question"],
                        active_task="reservation_request",
                        task_status="collecting_info",
                        reservation_frame={
                            "guest_name": "Patrik",
                            "date": "zajtra",
                            "time": "19:00",
                            "party_size": 2,
                        },
                        missing_fields=["phone"],
                        asked_fields=["phone"],
                    ),
                    reservation_decision(),
                    ReservationExtractionResult(
                        field_updates={"phone": "+421944015686"},
                        active_task="reservation_request",
                        task_status="ready_to_submit",
                    ),
                    TaskStateValidationResult(task_status="ready_to_submit"),
                    ResponseDraft(
                        response_text="Vašu žiadosť o rezerváciu sme prijali. Personál ju potvrdí."
                    ),
                    ok_response_validation(),
                ]
            )
        ),
        tenant_config_loader=TenantConfigLoader(),
        capability_router=FakeCapabilityRouter(),
        tool_call_repository=tool_call_repository,
        conversation_repository=conversation_repository,
    )

    first = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            content=(
                "Ahoj. Volam sa Patrik. Chcem urobit rezervaciu zajtra o 19 pre dvoch. "
                "Mate parkovanie?"
            ),
        )
    )
    first_conversation = conversation_repository.get_by_id(first.conversation_id)

    assert first.requested_capabilities == []
    assert first.tool_calls == []
    assert "Parkovanie je dostupné" in first.response_text
    assert "telefónne číslo" in first.response_text
    assert first.agent_trace["plan_capability"]["gate"]["missing_fields"] == ["phone"]
    assert first_conversation.metadata is None

    second = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            conversation_id=first.conversation_id,
            content="+421944015686",
        )
    )
    tool_calls = tool_call_repository.list_by_message_id(second.user_message.id)
    second_conversation = conversation_repository.get_by_id(second.conversation_id)
    frame = tool_calls[0].input["reservation_frame"]

    assert second.conversation_id == first.conversation_id
    assert second.requested_capabilities[0].name == "reservation.create_request"
    assert second.capability_results[0].status == "success"
    assert second.agent_trace["plan_capability"]["gate"]["can_submit"] is True
    assert tool_calls[0].provider == "google_sheets"
    assert frame["guest_name"] == "Patrik"
    assert frame["date"] == "zajtra"
    assert frame["time"] == "19:00"
    assert frame["party_size"] == 2
    assert frame["phone"] == "+421944015686"
    assert second_conversation.metadata is None


def test_opening_hours_direct_response_does_not_execute_capability():
    conversation_repository = InMemoryConversationRepository()
    message_repository = InMemoryMessageRepository()
    tool_call_repository = InMemoryToolCallRepository()
    use_case = ProcessIncomingMessage(
        message_repository=message_repository,
        agent_runtime=FakeOpeningHoursAgentRuntime(),
        tenant_config_loader=TenantConfigLoader(),
        capability_router=FakeCapabilityRouter(),
        tool_call_repository=tool_call_repository,
        conversation_repository=conversation_repository,
    )

    response = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            content="Kedy mate otvorene?",
        )
    )

    assert response.requested_capabilities == []
    assert response.tool_calls == []
    assert "10:00 - 21:00 every day except Sunday" in response.response_text
    assert response.assistant_message.content == response.response_text


def test_capability_success_user_message_overrides_premature_agent_response():
    use_case, _, _, _ = build_use_case(agent_response_text="PREMATURE SUCCESS")

    response = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            content="Chcem urobit rezervaciu.",
        )
    )

    assert response.response_text == "Vašu žiadosť o rezerváciu sme prijali. Personál ju potvrdí."


def test_message_creates_conversation_and_saves_user_assistant_and_tool_call():
    use_case, _, message_repository, tool_call_repository = build_use_case()

    response = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            content="Chcem urobit rezervaciu.",
        )
    )

    messages = message_repository.list_by_conversation_id(response.conversation_id)
    tool_calls = tool_call_repository.list_by_message_id(response.user_message.id)

    assert response.conversation_id
    assert response.user_message.conversation_id == response.conversation_id
    assert response.assistant_message.conversation_id == response.conversation_id
    assert [message.role for message in messages] == ["user", "assistant"]
    assert tool_calls[0].provider == "google_sheets"
    assert tool_calls[0].conversation_id == response.conversation_id


def test_next_message_continues_existing_conversation_by_id():
    use_case, _, message_repository, _ = build_use_case()
    first = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            content="Chcem urobit rezervaciu.",
        )
    )

    second = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            conversation_id=first.conversation_id,
            content="Pre styri osoby.",
        )
    )

    messages = message_repository.list_by_conversation_id(first.conversation_id)

    assert second.conversation_id == first.conversation_id
    assert [message.role for message in messages] == ["user", "assistant", "user", "assistant"]


def test_next_message_from_same_external_user_reuses_active_conversation():
    use_case, _, message_repository, _ = build_use_case()
    first = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            external_user_id="person-1",
            content="Ahoj",
        )
    )

    second = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            external_user_id="person-1",
            content="Dalsia sprava",
        )
    )

    messages = message_repository.list_by_conversation_id(first.conversation_id)

    assert second.conversation_id == first.conversation_id
    assert [message.role for message in messages] == ["user", "assistant", "user", "assistant"]


def test_provider_failure_is_saved_as_failed_tool_call_and_failed_messages():
    use_case, conversation_repository, _, tool_call_repository = build_use_case(CapabilityStatus.FAILED)

    response = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            content="Chcem urobit rezervaciu.",
        )
    )

    tool_calls = tool_call_repository.list_by_message_id(response.user_message.id)
    conversation = conversation_repository.get_by_id(response.conversation_id)

    assert response.status == "failed"
    assert response.user_message.status == "failed"
    assert response.assistant_message.status == "failed"
    assert response.capability_results[0].status == "failed"
    assert tool_calls[0].status == "failed"
    assert tool_calls[0].error == "provider failed"
    assert conversation.status == "failed"


def test_unknown_tenant_returns_loader_error():
    use_case, _, _, _ = build_use_case()

    try:
        use_case.execute(
            CreateMessageRequest(
                tenant_id="unknown_tenant",
                channel="chat",
                content="hello",
            )
        )
    except TenantConfigNotFoundError:
        return

    raise AssertionError("expected TenantConfigNotFoundError")


def test_conversation_messages_endpoint_handler_returns_history():
    use_case, conversation_repository, message_repository, _ = build_use_case()
    response = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            content="Chcem urobit rezervaciu.",
        )
    )

    history = list_conversation_messages(
        response.conversation_id,
        conversation_repository,
        message_repository,
    )

    assert history.conversation.id == response.conversation_id
    assert [message.role for message in history.messages] == ["user", "assistant"]
