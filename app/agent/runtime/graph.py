from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.agent.contracts.enums import ResponseMode
from app.agent.contracts.input import AgentInput
from app.agent.contracts.output import AgentResult
from app.agent.contracts.state import GraphState
from app.agent.nodes.build_chat_memory import BuildChatMemoryNode
from app.agent.nodes.decide_next_step import DecideNextStepNode
from app.agent.nodes.execute_capability import ExecuteCapabilityNode
from app.agent.nodes.extract_task_fields import ExtractTaskFieldsNode
from app.agent.nodes.finalize import FinalizeNode
from app.agent.nodes.load_context import LoadContextNode
from app.agent.nodes.plan_capability import PlanCapabilityNode
from app.agent.nodes.plan_response import PlanResponseNode
from app.agent.nodes.revise_response import ReviseResponseNode
from app.agent.nodes.validate_capability_request import ValidateCapabilityRequestNode
from app.agent.nodes.validate_capability_result import ValidateCapabilityResultNode
from app.agent.nodes.validate_decision import ValidateDecisionNode
from app.agent.nodes.validate_response import ValidateResponseNode
from app.agent.nodes.validate_task_state import ValidateTaskStateNode
from app.agent.profiles.loader import AgentProfileLoader
from app.agent.runtime.capability_executor import CapabilityExecutor


class AgentGraph:
    """LangGraph runtime for one agent turn."""

    def __init__(
        self,
        *,
        llm: BaseChatModel,
        profile_loader: AgentProfileLoader,
        capability_executor: CapabilityExecutor | None,
        max_decision_iterations: int,
        max_response_iterations: int,
    ):
        self.load_context = LoadContextNode(profile_loader)
        self.build_chat_memory = BuildChatMemoryNode(llm)
        self.decide_next_step = DecideNextStepNode(llm)
        self.validate_decision = ValidateDecisionNode(max_decision_iterations)
        self.extract_task_fields = ExtractTaskFieldsNode(llm)
        self.validate_task_state = ValidateTaskStateNode(llm)
        self.plan_capability = PlanCapabilityNode()
        self.validate_capability_request = ValidateCapabilityRequestNode()
        self.execute_capability = ExecuteCapabilityNode(capability_executor)
        self.validate_capability_result = ValidateCapabilityResultNode()
        self.plan_response = PlanResponseNode(llm)
        self.validate_response = ValidateResponseNode(llm)
        self.revise_response = ReviseResponseNode(self.plan_response)
        self.finalize = FinalizeNode()
        self.max_decision_iterations = max_decision_iterations
        self.max_response_iterations = max_response_iterations
        self.graph = self._compile_graph()

    def run(self, agent_input: AgentInput) -> AgentResult:
        result = self.graph.invoke(
            {
                "agent_input": agent_input,
                "decision_iteration": 1,
                "response_iteration": 1,
            }
        )
        return result["result"]

    def _compile_graph(self):
        graph = StateGraph(GraphState)
        graph.add_node("load_context", self._load_context)
        graph.add_node("build_chat_memory", self._build_chat_memory)
        graph.add_node("decide_next_step", self._decide_next_step)
        graph.add_node("validate_decision", self._validate_decision)
        graph.add_node("extract_task_fields", self._extract_task_fields)
        graph.add_node("validate_task_state", self._validate_task_state)
        graph.add_node("plan_capability", self._plan_capability)
        graph.add_node("validate_capability_request", self._validate_capability_request)
        graph.add_node("execute_capability", self._execute_capability)
        graph.add_node("validate_capability_result", self._validate_capability_result)
        graph.add_node("plan_response", self._plan_response)
        graph.add_node("validate_response", self._validate_response)
        graph.add_node("revise_response", self._revise_response)
        graph.add_node("finalize", self._finalize)

        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "build_chat_memory")
        graph.add_edge("build_chat_memory", "decide_next_step")
        graph.add_edge("decide_next_step", "validate_decision")
        graph.add_conditional_edges(
            "validate_decision",
            self._route_decision,
            {
                "retry_decision": "decide_next_step",
                "continue": "extract_task_fields",
            },
        )
        graph.add_edge("extract_task_fields", "validate_task_state")
        graph.add_edge("validate_task_state", "plan_capability")
        graph.add_edge("plan_capability", "validate_capability_request")
        graph.add_conditional_edges(
            "validate_capability_request",
            self._route_capability_request,
            {
                "execute_capability": "execute_capability",
                "respond": "plan_response",
            },
        )
        graph.add_edge("execute_capability", "validate_capability_result")
        graph.add_edge("validate_capability_result", "plan_response")
        graph.add_edge("plan_response", "validate_response")
        graph.add_conditional_edges(
            "validate_response",
            self._route_response,
            {
                "revise_response": "revise_response",
                "finish": "finalize",
            },
        )
        graph.add_edge("revise_response", "validate_response")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _load_context(self, graph_state: GraphState) -> GraphState:
        return {"state": self.load_context(graph_state["agent_input"])}

    def _build_chat_memory(self, graph_state: GraphState) -> GraphState:
        return {"state": self.build_chat_memory(graph_state["state"])}

    def _decide_next_step(self, graph_state: GraphState) -> GraphState:
        return {"state": self.decide_next_step(graph_state["state"])}

    def _validate_decision(self, graph_state: GraphState) -> GraphState:
        iteration = graph_state.get("decision_iteration", 1)
        state = self.validate_decision(graph_state["state"], iteration=iteration)
        return {"state": state, "decision_iteration": iteration + 1}

    def _extract_task_fields(self, graph_state: GraphState) -> GraphState:
        return {"state": self.extract_task_fields(graph_state["state"])}

    def _validate_task_state(self, graph_state: GraphState) -> GraphState:
        return {"state": self.validate_task_state(graph_state["state"])}

    def _plan_capability(self, graph_state: GraphState) -> GraphState:
        return {"state": self.plan_capability(graph_state["state"])}

    def _validate_capability_request(self, graph_state: GraphState) -> GraphState:
        return {"state": self.validate_capability_request(graph_state["state"])}

    def _execute_capability(self, graph_state: GraphState) -> GraphState:
        state = graph_state["state"]
        state.response_mode = ResponseMode.AFTER_CAPABILITY
        return {"state": self.execute_capability(state)}

    def _validate_capability_result(self, graph_state: GraphState) -> GraphState:
        return {"state": self.validate_capability_result(graph_state["state"])}

    def _plan_response(self, graph_state: GraphState) -> GraphState:
        return {"state": self.plan_response(graph_state["state"])}

    def _validate_response(self, graph_state: GraphState) -> GraphState:
        iteration = graph_state.get("response_iteration", 1)
        state = self.validate_response(graph_state["state"], iteration=iteration)
        return {"state": state, "response_iteration": iteration + 1}

    def _revise_response(self, graph_state: GraphState) -> GraphState:
        return {"state": self.revise_response(graph_state["state"])}

    def _finalize(self, graph_state: GraphState) -> GraphState:
        return {"result": self.finalize(graph_state["state"])}

    def _route_decision(self, graph_state: GraphState) -> str:
        if graph_state["state"].decision_validation.get("retry"):
            return "retry_decision"
        return "continue"

    def _route_capability_request(self, graph_state: GraphState) -> str:
        if graph_state["state"].requested_capabilities:
            return "execute_capability"
        return "respond"

    def _route_response(self, graph_state: GraphState) -> str:
        response_iteration = graph_state.get("response_iteration", 1)
        if (
            graph_state["state"].response_validation.get("needs_revision")
            and response_iteration <= self.max_response_iterations
        ):
            return "revise_response"
        return "finish"
