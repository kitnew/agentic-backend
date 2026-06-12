from langchain_core.messages import AIMessage, HumanMessage

from app.agent.nodes import CONDITIONAL_NODE_CLASSES, NODE_CLASSES
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
        "tenant_prompt": "Tenant: Demo Restaurant",
        "now": "2026-06-12T12:00:00+02:00",
        "datetime": "2026-06-12T12:00:00+02:00",
        "locale": "sk-SK",
        "date": "2026-06-12",
        "time": "12:00:00",
        "timezone": "Europe/Bratislava",
    }


def test_agent_modules_export_node_and_tool_classes():
    assert [node.__name__ for node in NODE_CLASSES] == [
        "PrepareInputNode",
        "LlmAgentNode",
        "ToolExecutionNode",
        "FinalizeNode",
    ]
    assert [node.__name__ for node in CONDITIONAL_NODE_CLASSES] == ["ShouldContinueNode"]
    assert [tool.__name__ for tool in TOOL_CLASSES] == [
        "CreateReservationTool",
        "GetBusinessInfoTool",
    ]
    assert [tool.name for tool in create_langchain_tools()] == [
        "create_reservation",
        "get_business_info",
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
    assert [list(event.keys())[0] for event in result["agent_trace"]["events"]] == [
        "prepare_input",
        "agent",
        "finalize",
    ]


def test_runtime_runs_tool_path_inside_langgraph():
    runtime = AgentRuntime(
        FakeLlm(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_business_info",
                            "args": {},
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
        "prepare_input",
        "agent",
        "tool",
        "agent",
        "finalize",
    ]


def test_prompt_loader_includes_profile_and_tenant_time():
    prompt = PromptLoader().build_system_prompt(agent_context())

    assert "restaurant" in prompt.lower()
    assert "sk-SK" in prompt
    assert "Europe/Bratislava" in prompt
    assert "2026-06-12" in prompt
