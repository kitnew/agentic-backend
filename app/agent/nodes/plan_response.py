import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agent.contracts.enums import ResponseMode
from app.agent.contracts.state import AgentWorkingState, ResponseDraft
from app.agent.policies.response import build_response_contract


class PlanResponseNode:
    def __init__(self, llm: BaseChatModel):
        self.structured_llm = llm.with_structured_output(ResponseDraft, method="function_calling")

    def __call__(self, state: AgentWorkingState) -> AgentWorkingState:
        try:
            draft = _coerce_model(
                self.structured_llm.invoke(
                    [
                        SystemMessage(content=state.system_prompt or ""),
                        SystemMessage(content=state.tenant_prompt or ""),
                        HumanMessage(content=_response_payload(state)),
                    ]
                ),
                ResponseDraft,
            )
            response_text = draft.response_text
            error = None
        except Exception as exc:
            response_text = None
            error = str(exc)

        state.response_text = response_text
        if state.capability_results:
            state.response_mode = ResponseMode.AFTER_CAPABILITY
        else:
            state.response_mode = ResponseMode.DIRECT
        state.trace.setdefault("plan_response", []).append(
            {
                "response_text": response_text,
                "error": error,
                "response_mode": state.response_mode.value,
            }
        )
        return state


def _response_payload(state: AgentWorkingState) -> str:
    payload = {
        "instruction": (
            "Generate one customer-facing response using only validated state and tenant facts. "
            "Answer current unanswered customer questions first. Continue an active reservation task only "
            "with missing fields or validation conflicts. Do not repeat answers already present in "
            "answered_questions unless the current message explicitly asks again. Do not ask for a field "
            "that is already present in memory.frame. Do not claim capability success unless a capability_result "
            "contains that outcome. Do not say a reservation is prepared, sent, created, confirmed, waiting "
            "for staff confirmation, or ready for staff unless capability_results contains that outcome. "
            "If response_contract.must_mention_validation_errors is true, explain those validation errors. "
            "If response_contract.must_ask_missing_fields is true, ask only for those missing fields. "
            "It is allowed to mention an already answered business fact when it explains an active task "
            "validation error; do not repeat it as a separate FAQ answer. "
            "If capability_result.user_message is present, use it as the source of the execution outcome. "
            "Return structured ResponseDraft only."
        ),
        "current_message": state.message_text,
        "chat_history": [message.model_dump(mode="json") for message in state.chat_history],
        "answered_questions": state.answered_questions,
        "current_question_intents": state.current_question_intents,
        "decision": state.decision.model_dump(mode="json"),
        "memory": state.memory.model_dump(mode="json"),
        "task_validation": state.task_validation,
        "capability_validation": state.capability_validation,
        "response_contract": build_response_contract(state),
        "capability_results": [result.model_dump(mode="json") for result in state.capability_results],
        "business_info": state.tenant_context.get("business_info") or {},
        "agent": state.tenant_agent,
        "response_validation_feedback": state.response_validation,
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
