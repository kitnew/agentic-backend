import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agent.contracts.state import AgentWorkingState, ResponseValidationResult
from app.agent.policies.response import build_response_contract, normalize_response_validation


class ValidateResponseNode:
    def __init__(self, llm: BaseChatModel):
        self.structured_llm = llm.with_structured_output(ResponseValidationResult, method="function_calling")

    def __call__(self, state: AgentWorkingState, *, iteration: int) -> AgentWorkingState:
        try:
            validation = _coerce_model(
                self.structured_llm.invoke(
                    [
                        SystemMessage(content=state.system_prompt or ""),
                        SystemMessage(content=state.tenant_prompt or ""),
                        HumanMessage(content=_validation_payload(state)),
                    ]
                ),
                ResponseValidationResult,
            )
            error = None
        except Exception as exc:
            validation = ResponseValidationResult(
                ok=False,
                needs_revision=True,
                issues=["response_validation_failed"],
                notes=[str(exc)],
            )
            error = str(exc)

        normalized = normalize_response_validation(state, validation)
        state.response_validation = normalized
        state.trace.setdefault("validate_response", []).append(
            {
                "iteration": iteration,
                "validation": normalized,
                "llm_validation": validation.model_dump(mode="json"),
                "error": error,
                "response_text": state.response_text,
            }
        )
        return state


def _validation_payload(state: AgentWorkingState) -> str:
    assistant_messages = [
        message.model_dump(mode="json")
        for message in state.chat_history
        if message.role == "assistant"
    ]
    payload = {
        "instruction": (
            "Validate the drafted customer response semantically. Reject it when it repeats already answered "
            "questions, asks for reservation fields already present in memory.frame, ignores current open "
            "questions, invents tenant facts, offers a new reservation task without active_task, claims capability "
            "success without capability_results, says a reservation is prepared/sent/created/confirmed/waiting "
            "for staff/ready for staff without capability_results, ignores validation_errors or missing_fields, "
            "or fails to mention capability failure. Set claims_capability_outcome=true for any response that "
            "implies an action was executed or handed to staff. Set claims_task_ready=true when it says the "
            "reservation is ready/prepared/complete. Set ignores_task_blockers=true when response_contract "
            "has blockers but the draft does not address them. Set asks_for_known_fields to any fields the "
            "draft asks for even though response_contract.known_reservation_fields contains them. "
            "Set asks_for_missing_fields as a boolean. Put the concrete missing fields asked by the draft "
            "into missing_fields_asked. Do not flag repeated answered questions when the draft uses an "
            "answered business fact only to explain an active task validation error. Return structured "
            "ResponseValidationResult only."
        ),
        "current_message": state.message_text,
        "assistant_history": assistant_messages,
        "answered_questions": state.answered_questions,
        "current_question_intents": state.current_question_intents,
        "decision": state.decision.model_dump(mode="json"),
        "memory": state.memory.model_dump(mode="json"),
        "task_validation": state.task_validation,
        "capability_validation": state.capability_validation,
        "response_contract": build_response_contract(state),
        "capability_results": [result.model_dump(mode="json") for result in state.capability_results],
        "business_info": state.tenant_context.get("business_info") or {},
        "draft_response": state.response_text,
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
