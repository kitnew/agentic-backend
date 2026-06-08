from app.agent.schemas import AgentOutput
from app.api.routes.conversations import list_conversation_messages
from app.application.messages.process_incoming_message import ProcessIncomingMessage
from app.capabilities.schemas import CapabilityRequest, CapabilityResult, CapabilityStatus
from app.domain.conversations.entities import Conversation
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
        return [
            message.model_copy()
            for message in self.messages.values()
            if message.conversation_id == conversation_id
        ]


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
    def run(self, agent_input):
        return AgentOutput(
            intent="reservation_request",
            response_text="",
            requested_capabilities=[
                CapabilityRequest(
                    name="reservation.create_request",
                    input={"raw_message": agent_input.message_text},
                )
            ],
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


def build_use_case(capability_status=CapabilityStatus.SUCCESS):
    conversation_repository = InMemoryConversationRepository()
    message_repository = InMemoryMessageRepository()
    tool_call_repository = InMemoryToolCallRepository()
    use_case = ProcessIncomingMessage(
        message_repository=message_repository,
        agent_runtime=FakeAgentRuntime(),
        tenant_config_loader=TenantConfigLoader(),
        capability_router=FakeCapabilityRouter(capability_status),
        tool_call_repository=tool_call_repository,
        conversation_repository=conversation_repository,
    )
    return use_case, conversation_repository, message_repository, tool_call_repository


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
    assert response.intent == "reservation_request"
    assert response.user_message.conversation_id == response.conversation_id
    assert response.assistant_message.conversation_id == response.conversation_id
    assert [message.role for message in messages] == ["user", "assistant"]
    assert tool_calls[0].provider == "google_sheets"
    assert tool_calls[0].conversation_id == response.conversation_id


def test_next_message_continues_existing_conversation():
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
