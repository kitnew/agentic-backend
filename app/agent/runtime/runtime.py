from langchain_core.messages import AIMessage, HumanMessage, message_to_dict

from app.agent.runtime.graph import create_agent_graph
from app.agent.runtime.serialization import serialize_event
from app.agent.schemas.context import AgentContext
from app.agent.schemas.input import AgentInput
from app.agent.schemas.output import AgentOutput
from app.core.timing import (
    finish_timing_trace,
    new_timing_trace,
    record_component_timing,
    start_timer,
)


class AgentRuntime:
    def __init__(self, llm, *, graph=None, tools=None, prompt_loader=None):
        self.llm = llm
        self.graph = graph
        self.tools = tools
        self.prompt_loader = prompt_loader

    def run(
        self,
        agent_input: AgentInput,
        *,
        context: AgentContext,
        tools=None,
    ) -> AgentOutput:
        total_timer = start_timer()
        timings = new_timing_trace()
        trace = {
            "input": serialize_event(agent_input),
            "context": dict(context),
            "events": [],
        }
        graph_input_timer = start_timer()
        graph_input = self._to_graph_input(agent_input)
        record_component_timing(timings, "graph_input_build", graph_input_timer)
        graph_build_timer = start_timer()
        graph = self._get_graph(tools=tools)
        record_component_timing(timings, "graph_build", graph_build_timer)
        graph_run_timer = start_timer()
        final_output = self._run_graph(graph, graph_input, context=context, trace=trace)
        record_component_timing(
            timings,
            "graph_run",
            graph_run_timer,
            event_count=len(trace["events"]),
        )
        finalization_timer = start_timer()
        response_text = final_output.get("response_text", "")
        response = final_output.get("response") or message_to_dict(AIMessage(content=response_text))

        trace["final_output"] = serialize_event(final_output)
        trace["graph"] = final_output.get("agent_trace", {})
        record_component_timing(timings, "finalization", finalization_timer)
        trace["timings"] = finish_timing_trace(timings, total_timer)

        return {
            "response_text": response_text,
            "response": response,
            "agent_trace": trace,
        }

    def _run_graph(
        self,
        graph,
        agent_input: AgentInput,
        *,
        context: AgentContext,
        trace: dict,
    ) -> dict:
        final_output: dict = {}

        for event in graph.stream(agent_input, context=context, stream_mode="updates"):
            trace["events"].append(serialize_event(event))
            if "finalize" in event:
                final_output = event["finalize"]

        return final_output

    def _to_graph_input(self, agent_input: AgentInput) -> dict:
        chat_history = list(agent_input.get("chat_history") or [])
        return {
            "messages": [
                *chat_history,
                HumanMessage(content=agent_input["message_text"]),
            ],
        }

    def _get_graph(self, *, tools=None):
        if tools is not None:
            return create_agent_graph(
                llm=self.llm,
                tools=tools,
                prompt_loader=self.prompt_loader,
            )
        if self.graph is None:
            self.graph = create_agent_graph(
                llm=self.llm,
                tools=self.tools,
                prompt_loader=self.prompt_loader,
            )
        return self.graph
