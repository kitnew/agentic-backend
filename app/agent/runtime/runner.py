from langchain_core.language_models.chat_models import BaseChatModel

from app.agent.contracts.input import AgentInput
from app.agent.contracts.output import AgentResult
from app.agent.profiles.loader import AgentProfileLoader
from app.agent.runtime.capability_executor import CapabilityExecutor
from app.agent.runtime.graph import AgentGraph


class AgentRuntime:
    """Public facade for the node-based agent graph."""

    def __init__(
        self,
        llm: BaseChatModel,
        profile_loader: AgentProfileLoader | None = None,
        *,
        max_decision_iterations: int = 2,
        max_response_iterations: int = 2,
    ):
        self.llm = llm
        self.profile_loader = profile_loader or AgentProfileLoader()
        self.max_decision_iterations = max(1, max_decision_iterations)
        self.max_response_iterations = max(1, max_response_iterations)

    def run(
        self,
        agent_input: AgentInput,
        capability_executor: CapabilityExecutor | None = None,
    ) -> AgentResult:
        graph = AgentGraph(
            llm=self.llm,
            profile_loader=self.profile_loader,
            capability_executor=capability_executor,
            max_decision_iterations=self.max_decision_iterations,
            max_response_iterations=self.max_response_iterations,
        )
        return graph.run(agent_input)
