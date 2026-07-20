from langchain_core.messages import AIMessage, HumanMessage

from app.agent.prompts.loader import PromptLoader
from app.agent.runtime import AgentRuntime
from app.agent.tools import TOOL_CLASSES, create_langchain_tools


class FakeLlm:
    def __init__(self, responses):
        self.responses = list(responses)

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        return self.responses.pop(0)


class CapturingFakeLlm(FakeLlm):
    def __init__(self, responses):
        super().__init__(responses)
        self.messages = []

    def invoke(self, messages):
        self.messages.append(messages)
        return super().invoke(messages)


def agent_context():
    return {
        "tenant_id": "demo_restaurant",
        "conversation_id": "conversation-1",
        "agent_profile": "restaurant_assistant",
        "now": "2026-06-12T12:00:00+02:00",
        "datetime": "2026-06-12T12:00:00+02:00",
        "locale": "sk-SK",
        "date": "2026-06-12",
        "time": "12:00:00",
        "timezone": "Europe/Bratislava",
        "agent_style_rules": ["Keep answers short and clear."],
        "tenant_instructions": "You represent Demo Restaurant.",
        "business_info": {
            "opening_hours_text": "10:00 - 21:00 every day except Sunday",
            "address": "Demo ulica 12, Bratislava",
        },
        "reservation_policy": (
            "Reservation handling is request-only.\n"
            "Describe reservations as submitted requests waiting for staff confirmation."
        ),
        "required_reservation_fields": [
            "guest_name: name for the reservation",
            "phone: phone number",
        ],
        "schedule_summary": "monday: 10:00-21:00\nsunday: closed",
        "supported_operations": "- New reservation submission: supported",
    }


def test_agent_tools_remain_available_to_manual_runtime():
    assert [tool.__name__ for tool in TOOL_CLASSES] == [
        "CreateReservationTool",
        "CheckRoomAvailabilityTool",
    ]
    assert [tool.name for tool in create_langchain_tools()] == [
        "create_reservation",
        "check_room_availability",
    ]


def test_runtime_runs_direct_agent_path_with_agent_input_and_output():
    llm = CapturingFakeLlm([AIMessage(content="ok")])
    runtime = AgentRuntime(llm)

    result = runtime.run(
        {
            "message_text": "hello",
            "chat_history": [HumanMessage(content="previous")],
        },
        context=agent_context(),
    )

    assert result["response_text"] == "ok"
    assert result["response"]["type"] == "ai"
    assert [message.content for message in llm.messages[0] if message.type == "human"] == [
        "previous",
        "hello",
    ]
    assert [list(event.keys())[0] for event in result["agent_trace"]["events"]] == ["llm"]


def test_runtime_runs_direct_provider_tool_loop():
    runtime = AgentRuntime(
        FakeLlm(
            [
                AIMessage(
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
                ),
                AIMessage(content="Business info loaded"),
            ]
        )
    )

    result = runtime.run({"message_text": "What are your hours?"}, context=agent_context())

    assert result["response_text"] == "Business info loaded"
    assert [list(event.keys())[0] for event in result["agent_trace"]["events"]] == [
        "llm",
        "tool",
        "llm",
    ]


def test_prompt_loader_includes_profile_and_tenant_time():
    prompt = PromptLoader().build_system_prompt(agent_context())

    assert "restaurant" in prompt.lower()
    assert "sk-SK" in prompt
    assert "Europe/Bratislava" in prompt
    assert "2026-06-12" in prompt
    assert "opening_hours_text" in prompt
    assert "request-only" in prompt
    assert "submitted requests waiting for staff confirmation" in prompt
    assert "New reservation submission: supported" in prompt
    assert "reservation.create_request" not in prompt
    assert "spreadsheet_id" not in prompt
    assert "sheet_name" not in prompt
