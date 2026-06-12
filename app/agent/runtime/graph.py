from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    FinalizeNode,
    LlmAgentNode,
    ShouldContinueNode,
    ToolExecutionNode,
)
from app.agent.prompts.loader import PromptLoader
from app.agent.schemas.context import AgentContext
from app.agent.schemas.input import AgentGraphInput
from app.agent.schemas.output import AgentOutput
from app.agent.schemas.state import AgentState
from app.agent.tools import create_langchain_tools


class AgentGraphBuilder:
    def __init__(
        self,
        llm,
        *,
        tools=None,
        prompt_loader: PromptLoader | None = None,
    ):
        self.llm = llm
        self.tools = create_langchain_tools() if tools is None else tools
        self.prompt_loader = prompt_loader or PromptLoader()

    def build(self):
        agent = LlmAgentNode(
            llm=self.llm,
            tools=self.tools,
            prompt_loader=self.prompt_loader,
        )
        tool = ToolExecutionNode(self.tools)
        finalize = FinalizeNode()
        should_continue = ShouldContinueNode()

        graph = StateGraph(
            state_schema=AgentState,
            input_schema=AgentGraphInput,
            output_schema=AgentOutput,
            context_schema=AgentContext,
        )
        graph.add_node(agent.name, agent)
        graph.add_node(tool.name, tool)
        graph.add_node(finalize.name, finalize)

        graph.add_edge(START, agent.name)
        graph.add_conditional_edges(
            agent.name,
            should_continue,
            {
                "end": finalize.name,
                "continue": tool.name,
            },
        )
        graph.add_edge(tool.name, agent.name)
        graph.add_edge(finalize.name, END)

        return graph.compile()


def create_agent_graph(llm, *, tools=None, prompt_loader: PromptLoader | None = None):
    return AgentGraphBuilder(
        llm=llm,
        tools=tools,
        prompt_loader=prompt_loader,
    ).build()
