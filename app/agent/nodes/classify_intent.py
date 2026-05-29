from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AgentState
from app.agent.schemas import IntentClassifierOutput


SYSTEM_PROMPT = """
You classify the intent of a user message.
Return only a short intent name in snake_case.
Use simple labels like: reservation_request, opening_hours, menu_question, contact_request, complaint, human_handoff, unknown
""".strip()


def build_classify_intent_node(llm: BaseChatModel):
    structured_llm = llm.with_structured_output(IntentClassifierOutput)

    def classify_intent(state: AgentState) -> AgentState:
        result = structured_llm.invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=state["message_text"]),
            ]
        )

        return AgentState(
            tenant_id=state["tenant_id"],
            conversation_id=state["conversation_id"],
            message_id=state["message_id"],
            message_text=state["message_text"],
            intent=result.intent,
            response_text=result.response_text,
            requested_capabilities=result.requested_capabilities,
            metadata=state["metadata"],
        )

    return classify_intent