import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agent.contracts.enums import AgentTaskName
from app.agent.contracts.state import AgentWorkingState, ReservationExtractionResult
from app.agent.tasks.reservation.frame import clean_reservation_frame, merge_reservation_frame


class ExtractTaskFieldsNode:
    def __init__(self, llm: BaseChatModel):
        self.structured_llm = llm.with_structured_output(ReservationExtractionResult, method="function_calling")

    def __call__(self, state: AgentWorkingState) -> AgentWorkingState:
        if (
            state.decision.active_task != AgentTaskName.RESERVATION_REQUEST
            and state.memory.active_task != AgentTaskName.RESERVATION_REQUEST
        ):
            state.trace["extract_task_fields"] = {"skipped": True, "reason": "no_active_task"}
            return state

        try:
            extraction = _coerce_model(
                self.structured_llm.invoke(
                    [
                        SystemMessage(content=state.system_prompt or ""),
                        SystemMessage(content=state.tenant_prompt or ""),
                        HumanMessage(content=_extraction_payload(state)),
                    ]
                ),
                ReservationExtractionResult,
            )
            error = None
        except Exception as exc:
            extraction = ReservationExtractionResult()
            error = str(exc)

        frame = merge_reservation_frame(state.memory.frame, extraction.field_updates).model_dump(mode="json")
        state.memory.frame = clean_reservation_frame(frame)
        state.memory.active_task = (
            extraction.active_task
            or state.memory.active_task
            or AgentTaskName.RESERVATION_REQUEST
        )
        if extraction.task_status:
            state.memory.task_status = extraction.task_status
        if extraction.missing_fields:
            state.memory.missing_fields = extraction.missing_fields
        if extraction.validation_errors:
            state.memory.validation_errors = extraction.validation_errors
        state.memory.user_confirmed = state.memory.user_confirmed or extraction.user_confirmed
        state.trace["extract_task_fields"] = {
            "skipped": False,
            "error": error,
            "extraction": extraction.model_dump(mode="json"),
            "frame": state.memory.frame,
        }
        return state


def _extraction_payload(state: AgentWorkingState) -> str:
    payload = {
        "instruction": (
            "Extract reservation field updates semantically from the current message in context. "
            "Understand corrections, confirmations, pronouns, party size phrasing, and colloquial language. "
            "Do not drop existing current_frame values unless the user clearly corrects them. "
            "Do not infer a phone number from phrases like 'same number' unless an explicit caller phone "
            "is available in structured input. "
            "Return only structured fields; do not generate a customer response."
        ),
        "current_message": state.message_text,
        "chat_history": [message.model_dump(mode="json") for message in state.chat_history],
        "current_frame": state.memory.frame,
        "current_task_status": state.memory.task_status,
        "reservation_required_fields": (state.tenant_context.get("reservation") or {}).get("required_fields") or [],
        "allowed_active_task_values": ["reservation_request"],
        "allowed_task_status_values": [
            "collecting_info",
            "blocked_by_validation",
            "ready_to_submit",
            "submitted",
            "failed",
        ],
        "tenant_business_info": state.tenant_context.get("business_info") or {},
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
