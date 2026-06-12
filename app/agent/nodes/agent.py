from app.agent.schemas.state import AgentState
from app.agent.prompts.loader import load_system_prompt

def agent(state: AgentState) -> AgentState:
    system_prompt = load_system_prompt()

    return ""