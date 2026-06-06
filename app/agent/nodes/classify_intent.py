from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AgentState
from app.agent.schemas import IntentClassifierOutput


SYSTEM_PROMPT = """
You classify the intent of a user message.
Return a structured result with intent, response_text, and requested_capabilities.
Use simple labels like: reservation_request, opening_hours, menu_question, contact_request, complaint, human_handoff, unknown
Use tenant context as the source of business facts such as opening hours.
For reservation_request, request reservation.create_request with input.raw_message equal to the original user message.
""".strip()


def build_classify_intent_node(llm: BaseChatModel):
    structured_llm = llm.with_structured_output(
        IntentClassifierOutput,
        method="function_calling",
    )

    def classify_intent(state: AgentState) -> AgentState:
        tenant_context = state["tenant_context"]
        tenant_prompt = f"""
Tenant context:
- tenant_id: {tenant_context["tenant_id"]}
- name: {tenant_context["name"]}
- business_type: {tenant_context["business_type"]}
- default_language: {tenant_context["default_language"]}
- timezone: {tenant_context["timezone"]}
- agent_profile: {tenant_context["agent_profile"]}
- business_info: {tenant_context["business_info"]}
- capabilities: {tenant_context["capabilities"]}
- policies: {tenant_context["policies"]}
""".strip()

        result = structured_llm.invoke(
            [
                SystemMessage(content=f"{SYSTEM_PROMPT}\n\n{tenant_prompt}"),
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
            tenant_context=state["tenant_context"],
        )

    return classify_intent
