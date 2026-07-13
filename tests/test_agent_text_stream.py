from types import SimpleNamespace

from app.agent.runtime.runtime import AgentRuntime


class Graph:
    def stream(self, *_args, **kwargs):
        assert kwargs["stream_mode"] == ["messages", "updates"]
        yield "messages", (
            SimpleNamespace(content="Ahoj ", tool_calls=[], tool_call_chunks=[]),
            {"langgraph_node": "agent"},
        )
        yield "messages", (
            SimpleNamespace(content="", tool_calls=[{"name": "tool"}], tool_call_chunks=[]),
            {"langgraph_node": "agent"},
        )
        yield "updates", {"finalize": {"response_text": "Ahoj svet"}}


def test_agent_runtime_forwards_only_agent_text_and_keeps_final_output():
    deltas = []
    output = AgentRuntime(None, graph=Graph()).run(
        {"message_text": "hi", "chat_history": []}, context={}, text_callback=deltas.append
    )
    assert deltas == ["Ahoj "]
    assert output["response_text"] == "Ahoj svet"
