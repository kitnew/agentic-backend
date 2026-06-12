from app.agent.schemas.state import AgentState

def should_continue(state: AgentState):
    messages = state["message_history"]
    last_message = messages[-1]
    if not last_message.tool_calls:
        return "end"
    else:
        return "continue"