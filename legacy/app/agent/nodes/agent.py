from langchain_core.messages import SystemMessage
from langgraph.runtime import Runtime

from app.agent.nodes.base import AgentNode
from app.agent.prompts.loader import PromptLoader
from app.agent.schemas.context import AgentContext
from app.agent.schemas.state import AgentState


class LlmAgentNode(AgentNode):
    name = "agent"

    def __init__(self, llm, tools, prompt_loader: PromptLoader | None = None):
        self.model = llm.bind_tools(tools)
        self.prompt_loader = prompt_loader or PromptLoader()

    def __call__(
        self,
        state: AgentState,
        runtime: Runtime[AgentContext],
    ) -> AgentState:
        context = runtime.context or {}
        system_prompt = self.prompt_loader.build_system_prompt(context)
        messages = [SystemMessage(content=system_prompt), *state["messages"]]
        response = self.model.invoke(messages)

        return {"messages": [response]}
