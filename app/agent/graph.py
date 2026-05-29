from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.agent.nodes.classify_intent import build_classify_intent_node
from app.agent.state import AgentState


def build_agent(llm: BaseChatModel):
    graph = StateGraph(AgentState)

    graph.add_node("classify_intent", build_classify_intent_node(llm))
    
    graph.add_edge(START, "classify_intent")
    
    graph.add_edge("classify_intent", END)

    return graph.compile()