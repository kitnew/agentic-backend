import json

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    message_chunk_to_message,
    message_to_dict,
)

from app.agent.prompts.loader import PromptLoader
from app.agent.runtime.serialization import message_content_to_text, serialize_event
from app.agent.schemas.context import AgentContext
from app.agent.schemas.input import AgentInput
from app.agent.schemas.output import AgentOutput
from app.core.timing import finish_timing_trace, new_timing_trace, record_component_timing, start_timer


class AgentRuntime:
    """Small provider-native tool loop used by the HTTP/manual message path."""

    def __init__(self, llm, *, tools=None, prompt_loader=None, max_tool_steps: int = 3):
        self.llm = llm
        self.tools = tools
        self.prompt_loader = prompt_loader or PromptLoader()
        self.max_tool_steps = max_tool_steps

    def run(self, agent_input: AgentInput, *, context: AgentContext, tools=None, text_callback=None) -> AgentOutput:
        total_timer = start_timer()
        timings = new_timing_trace()
        messages = [
            SystemMessage(content=self.prompt_loader.build_system_prompt(context)),
            *(agent_input.get("chat_history") or []),
            HumanMessage(content=agent_input["message_text"]),
        ]
        active_tools = list((self.tools if tools is None else tools) or [])
        model = self.llm.bind_tools(active_tools)
        tools_by_name = {tool.name: tool for tool in active_tools}
        events = []

        runtime_timer = start_timer()
        response = AIMessage(content="")
        for step in range(self.max_tool_steps + 1):
            response = self._invoke(model, messages, text_callback)
            events.append({"llm": serialize_event(response)})
            messages.append(response)
            if not response.tool_calls:
                break
            if step == self.max_tool_steps:
                raise RuntimeError("maximum tool steps exceeded")
            for call in response.tool_calls:
                tool = tools_by_name.get(call["name"])
                result = (
                    tool.invoke(call["args"])
                    if tool is not None
                    else {"status": "failed", "error": "tool is not available"}
                )
                tool_message = ToolMessage(
                    content=json.dumps(result, default=str, ensure_ascii=False),
                    tool_call_id=call["id"],
                    name=call["name"],
                )
                messages.append(tool_message)
                events.append({"tool": serialize_event(tool_message)})
        record_component_timing(timings, "llm_tool_loop", runtime_timer, event_count=len(events))

        response_text = message_content_to_text(response.content)
        return {
            "response_text": response_text,
            "response": message_to_dict(response),
            "agent_trace": {
                "input": serialize_event(agent_input),
                "context": dict(context),
                "events": events,
                "final_output": serialize_event(response),
                "timings": finish_timing_trace(timings, total_timer),
            },
        }

    @staticmethod
    def _invoke(model, messages, text_callback):
        if text_callback is None or not hasattr(model, "stream"):
            response = model.invoke(messages)
            if text_callback and (text := message_content_to_text(response.content)):
                text_callback(text)
            return response

        combined = None
        for chunk in model.stream(messages):
            combined = chunk if combined is None else combined + chunk
            if not getattr(chunk, "tool_call_chunks", None):
                text = message_content_to_text(chunk.content)
                if text:
                    text_callback(text)
        return AIMessage(content="") if combined is None else message_chunk_to_message(combined)
