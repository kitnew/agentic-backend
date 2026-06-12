from langgraph.graph import StateGraph, START, END
from app.agent.nodes.agent import agent
from app.agent.nodes.tool import tool
from app.agent.nodes.should_continue import  should_continue


from app.agent.schemas.state import AgentState
from app.agent.schemas.input import AgentInput
from app.agent.schemas.output import AgentOutput
from app.agent.schemas.context import AgentContext

graph = StateGraph(
    state_schema=AgentState,
    input_schema=AgentInput,
    output_schema=AgentOutput,
    context_schema=AgentContext
)
graph.add_node("agent", agent)
graph.add_node("tool", tool)

graph.add_edge(START, "agent")

graph.add_conditional_edge(
    "agent",
    should_continue,
    {
        "end": END,
        "continue": "agent"
    }
)

graph.compile()