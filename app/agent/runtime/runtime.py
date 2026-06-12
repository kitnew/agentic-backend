from langchain_core.messages import AIMessage, HumanMessage, message_to_dict

from app.agent.runtime.graph import create_agent_graph
from app.agent.runtime.serialization import serialize_event
from app.agent.schemas.context import AgentContext
from app.agent.schemas.input import AgentInput
from app.agent.schemas.output import AgentOutput


class AgentRuntime:
    def __init__(self, llm, *, graph=None, tools=None, prompt_loader=None):
        self.graph = graph or create_agent_graph(
            llm=llm,
            tools=tools,
            prompt_loader=prompt_loader,
        )

    def run(
        self,
        agent_input: AgentInput,
        *,
        context: AgentContext,
    ) -> AgentOutput:
        trace = {
            "input": serialize_event(agent_input),
            "context": dict(context),
            "events": [],
        }
        graph_input = self._to_graph_input(agent_input)
        final_output = self._run_graph(graph_input, context=context, trace=trace)
        response_text = final_output.get("response_text", "")
        response = final_output.get("response") or message_to_dict(AIMessage(content=response_text))

        trace["final_output"] = serialize_event(final_output)
        trace["graph"] = final_output.get("agent_trace", {})

        return {
            "response_text": response_text,
            "response": response,
            "agent_trace": trace,
        }

    def _run_graph(
        self,
        agent_input: AgentInput,
        *,
        context: AgentContext,
        trace: dict,
    ) -> dict:
        final_output: dict = {}

        for event in self.graph.stream(agent_input, context=context, stream_mode="updates"):
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
