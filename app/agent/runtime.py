from langchain_core.language_models.chat_models import BaseChatModel

from app.agent.graph import build_agent
from app.agent.state import AgentState
from app.agent.schemas import AgentInput, AgentOutput
from app.capabilities.schemas import CapabilityRequest

class AgentRuntime:
    """
    Runtime execution class for the LangGraph agent.
    Bridges Pydantic schemas (AgentInput, AgentOutput) with the internal
    LangGraph AgentState representation.
    """
    def __init__(self, llm: BaseChatModel):
        self.agent = build_agent(llm)

    def run(self, agent_input: AgentInput) -> AgentOutput:
        # Convert Pydantic AgentInput to internal AgentState TypedDict
        state = AgentState(
            tenant_id=agent_input.tenant_id,
            conversation_id=agent_input.conversation_id or "",
            message_id=agent_input.message_id or "",
            message_text=agent_input.message_text,
            intent=None,
            response_text=None,
            requested_capabilities=[],
            metadata=agent_input.metadata,
            tenant_context=agent_input.tenant_context.model_dump(),
        )

        # Invoke the LangGraph agent execution
        result_state = self.agent.invoke(state)

        # Return validated AgentOutput Pydantic model
        requested_capabilities = result_state.get("requested_capabilities") or []
        if result_state.get("intent") == "reservation_request" and not requested_capabilities:
            requested_capabilities = [
                CapabilityRequest(
                    name="reservation.create_request",
                    input={"raw_message": agent_input.message_text},
                )
            ]

        return AgentOutput(
            intent=result_state.get("intent") or "unknown",
            response_text=result_state.get("response_text") or "",
            requested_capabilities=requested_capabilities,
            metadata=result_state.get("metadata"),
        )
