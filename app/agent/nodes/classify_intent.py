from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.schemas import IntentClassification
from app.agent.state import AgentState


SYSTEM_PROMPT = """
You classify the intent of a user message.
Return only a short intent name in snake_case.
Use simple labels like: reservation, question, complaint, greeting, other.
""".strip()


def build_classify_intent_node(llm: BaseChatModel):
    structured_llm = llm.with_structured_output(IntentClassification)

    def classify_intent(state: AgentState) -> dict[str, str]:
        result = structured_llm.invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=state["message"]),
            ]
        )

        return {"intent": result.intent}

    return classify_intent
