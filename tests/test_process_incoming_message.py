from langchain_core.messages import AIMessage

from app.agent.runtime import AgentRuntime
from app.api.routes.conversations import list_conversation_messages
from app.application.messages.process_incoming_message import ProcessIncomingMessage
from app.capabilities.schemas import CapabilityResult, CapabilityStatus
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


class FakeCapabilityRouter:
    def __init__(self, status=CapabilityStatus.SUCCESS):
        self.status = status
        self.requests = []

    def execute(self, tenant_context, capability_request):
        self.requests.append(capability_request)
        return CapabilityResult(
            name=capability_request.name,
            status=self.status,
            provider="fake",
            output={
                "row_appended": self.status == CapabilityStatus.SUCCESS,
                "reservation_frame": capability_request.input.get("reservation_frame"),
            },
            user_message="Vašu žiadosť o rezerváciu sme prijali. Personál ju potvrdí.",
            error="provider failed" if self.status == CapabilityStatus.FAILED else None,
        )


class FakeAgentRuntime:
    def __init__(self, response_text: str = "Agent response"):
        self.response_text = response_text
        self.inputs = []
        self.contexts = []

    def run(self, agent_input, *, context, tools=None):
        self.inputs.append(agent_input)
        self.contexts.append(context)
        return {
            "response_text": self.response_text,
            "response": {
                "type": "ai",
                "data": {"content": self.response_text},
            },
            "agent_trace": {
                "chat_history_count": len(agent_input.get("chat_history") or []),
                "context": context,
            },
        }


class FakeToolCallingLlm:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "create_reservation",
                        "args": {
                            "guest_name": "Patrik",
                            "date": "zajtra",
                            "time": "19:00",
                            "party_size": 2,
                            "phone": "+421900123456",
                        },
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(
            content="Vašu žiadosť o rezerváciu sme prijali. Personál ju potvrdí."
        )


def build_use_case(response_text: str = "Agent response"):
    conversation_repository = InMemoryConversationRepository()
    message_repository = InMemoryMessageRepository()
    tool_call_repository = InMemoryToolCallRepository()
    agent_runtime = FakeAgentRuntime(response_text)
    use_case = ProcessIncomingMessage(
        message_repository=message_repository,
        agent_runtime=agent_runtime,
        tenant_config_loader=TenantConfigLoader(),
        capability_router=FakeCapabilityRouter(),
        tool_call_repository=tool_call_repository,
        conversation_repository=conversation_repository,
    )
    return use_case, conversation_repository, message_repository, agent_runtime


def test_message_creates_conversation_and_uses_agent_input_output_contract():
    use_case, _, message_repository, agent_runtime = build_use_case("Ahoj")

    response = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            content="Hello",
        )
    )

    messages = message_repository.list_by_conversation_id(response.conversation_id)

    assert response.response_text == "Ahoj"
    assert response.assistant_message.content == "Ahoj"
    assert [message.role for message in messages] == ["user", "assistant"]
    assert agent_runtime.inputs[0]["message_text"] == "Hello"
    assert agent_runtime.inputs[0]["chat_history"] == []
    assert agent_runtime.contexts[0]["agent_profile"] == "restaurant_assistant"
    assert agent_runtime.contexts[0]["locale"] == "sk-SK"
    assert agent_runtime.contexts[0]["timezone"] == "Europe/Bratislava"
    assert "opening_hours_text" in agent_runtime.contexts[0]["business_info"]
    assert "request_only" in agent_runtime.contexts[0]["reservation_policy"]
    assert "submitted requests waiting for staff confirmation" in agent_runtime.contexts[0]["reservation_policy"]
    assert "guest_name: name for the reservation" in agent_runtime.contexts[0]["required_reservation_fields"]
    assert "sunday: closed" in agent_runtime.contexts[0]["schedule_summary"]
    assert agent_runtime.contexts[0]["enabled_capabilities"] == ["reservation.create_request"]
    assert response.agent_trace["context"]["tenant_id"] == "demo_restaurant"


def test_next_message_continues_existing_conversation_with_chat_history():
    use_case, _, message_repository, agent_runtime = build_use_case()
    first = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            content="First",
        )
    )

    second = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            conversation_id=first.conversation_id,
            content="Second",
        )
    )

    messages = message_repository.list_by_conversation_id(first.conversation_id)

    assert second.conversation_id == first.conversation_id
    assert [message.role for message in messages] == ["user", "assistant", "user", "assistant"]
    assert agent_runtime.inputs[1]["message_text"] == "Second"
    assert len(agent_runtime.inputs[1]["chat_history"]) == 2
    assert second.agent_trace["chat_history_count"] == 2


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


def test_agent_tool_executes_reservation_capability_and_saves_tool_call():
    conversation_repository = InMemoryConversationRepository()
    message_repository = InMemoryMessageRepository()
    tool_call_repository = InMemoryToolCallRepository()
    capability_router = FakeCapabilityRouter()
    use_case = ProcessIncomingMessage(
        message_repository=message_repository,
        agent_runtime=AgentRuntime(FakeToolCallingLlm()),
        tenant_config_loader=TenantConfigLoader(),
        capability_router=capability_router,
        tool_call_repository=tool_call_repository,
        conversation_repository=conversation_repository,
    )

    response = use_case.execute(
        CreateMessageRequest(
            tenant_id="demo_restaurant",
            channel="chat",
            content="Chcem rezerváciu zajtra o 19 pre dvoch. Volám sa Patrik.",
        )
    )
    tool_calls = tool_call_repository.list_by_message_id(response.user_message.id)

    assert response.requested_capabilities[0].name == "reservation.create_request"
    assert response.capability_results[0].status == "success"
    assert response.tool_calls[0].id == tool_calls[0].id
    assert capability_router.requests[0].input["reservation_frame"]["guest_name"] == "Patrik"
    assert tool_calls[0].capability_name == "reservation.create_request"
    assert tool_calls[0].provider == "fake"
    assert response.response_text == "Vašu žiadosť o rezerváciu sme prijali. Personál ju potvrdí."


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
            content="Hello",
        )
    )

    history = list_conversation_messages(
        response.conversation_id,
        conversation_repository,
        message_repository,
    )

    assert history.conversation.id == response.conversation_id
    assert [message.role for message in history.messages] == ["user", "assistant"]
