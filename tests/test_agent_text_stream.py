from langchain_core.messages import AIMessageChunk

from app.agent.runtime.runtime import AgentRuntime


class StreamingLlm:
    def bind_tools(self, _tools):
        return self

    def stream(self, _messages):
        yield AIMessageChunk(content="Ahoj ")
        yield AIMessageChunk(content="svet")


def test_agent_runtime_forwards_native_provider_chunks_and_keeps_final_output():
    deltas = []
    output = AgentRuntime(StreamingLlm()).run(
        {"message_text": "hi", "chat_history": []},
        context={
            "tenant_id": "tenant",
            "agent_profile": "restaurant_assistant",
            "datetime": "2026-01-01T12:00:00+00:00",
            "date": "2026-01-01",
            "time": "12:00:00",
            "locale": "en",
            "timezone": "UTC",
            "agent_style_rules": [],
            "tenant_instructions": "",
            "business_info": {},
            "reservation_policy": "",
            "required_reservation_fields": [],
            "schedule_summary": "",
        },
        text_callback=deltas.append,
    )
    assert deltas == ["Ahoj ", "svet"]
    assert output["response_text"] == "Ahoj svet"
