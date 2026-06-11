import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agent.contracts.state import AgentDecision, AgentWorkingState


class DecideNextStepNode:
    def __init__(self, llm: BaseChatModel):
        self.structured_llm = llm.with_structured_output(AgentDecision, method="function_calling")

    def __call__(self, state: AgentWorkingState) -> AgentWorkingState:
        try:
            decision = _coerce_model(
                self.structured_llm.invoke(
                    [
                        SystemMessage(content=state.system_prompt or ""),
                        SystemMessage(content=state.tenant_prompt or ""),
                        HumanMessage(content=_decision_payload(state)),
                    ]
                ),
                AgentDecision,
            )
            error = None
        except Exception as exc:
            decision = AgentDecision()
            error = str(exc)

        state.decision = decision
        state.trace.setdefault("decide_next_step", []).append(
            {
                "raw_decision": decision.model_dump(mode="json"),
                "error": error,
                "feedback": state.decision_feedback,
            }
        )
        return state


def _decision_payload(state: AgentWorkingState) -> str:
    payload = {
        "instruction": (
            "Decide only what the customer currently asks or provides. Do not offer reservation "
            "collection unless the customer asks for a reservation or the chat already has an active "
            "reservation task. Return structured AgentDecision only."
        ),
        "current_message": state.message_text,
        "chat_history": [message.model_dump(mode="json") for message in state.chat_history],
        "answered_questions": state.answered_questions,
        "current_question_intents": state.current_question_intents,
        "current_reservation_fields": state.current_reservation_fields,
        "memory": state.memory.model_dump(mode="json"),
        "supported_intents": state.profile.get("supported_intents") or [],
        "tenant_business_info": state.tenant_context.get("business_info") or {},
        "feedback_from_validation": state.decision_feedback,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _coerce_model(value: Any, model: type[BaseModel]) -> Any:
    if isinstance(value, model):
        return value
    if isinstance(value, BaseModel):
        return model.model_validate(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return model.model_validate(value)
    return model.model_validate(value)
