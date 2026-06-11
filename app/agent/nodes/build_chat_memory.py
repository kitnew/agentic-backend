import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agent.contracts.state import AgentWorkingState, ChatMemoryExtraction, ReservationMemory
from app.agent.tasks.reservation.frame import clean_reservation_frame, merge_reservation_frame


class BuildChatMemoryNode:
    def __init__(self, llm: BaseChatModel):
        self.structured_llm = llm.with_structured_output(ChatMemoryExtraction, method="function_calling")

    def __call__(self, state: AgentWorkingState) -> AgentWorkingState:
        try:
            extraction = _coerce_model(
                self.structured_llm.invoke(
                    [
                        SystemMessage(content=state.system_prompt or ""),
                        SystemMessage(content=state.tenant_prompt or ""),
                        HumanMessage(content=_memory_payload(state)),
                    ]
                ),
                ChatMemoryExtraction,
            )
            error = None
        except Exception as exc:
            extraction = ChatMemoryExtraction()
            error = str(exc)

        state.answered_questions = extraction.answered_questions
        state.current_question_intents = extraction.current_question_intents
        state.current_reservation_fields = clean_reservation_frame(extraction.current_reservation_fields)
        reservation_frame = merge_reservation_frame(
            extraction.reservation_frame,
            state.current_reservation_fields,
        ).model_dump(mode="json")
        state.memory = ReservationMemory(
            frame=clean_reservation_frame(reservation_frame),
            missing_fields=extraction.missing_fields,
            validation_errors=extraction.validation_errors,
            active_task=extraction.active_task,
            task_status=extraction.task_status,
            asked_fields=extraction.asked_fields,
            field_attempt_count=extraction.field_attempt_count,
            user_confirmed=extraction.user_confirmed,
        )
        state.trace["build_chat_memory"] = {
            "error": error,
            "extraction": extraction.model_dump(mode="json"),
            "memory": state.memory.model_dump(mode="json"),
        }
        return state


def _memory_payload(state: AgentWorkingState) -> str:
    payload = {
        "instruction": (
            "Extract conversation memory semantically. Identify already answered factual questions, "
            "current user questions, active reservation task if any, reservation frame across history, "
            "fields already asked by the assistant, and whether the user confirmed a pending reservation. "
            "Durable user-provided identity and reservation fields from earlier messages must remain in "
            "reservation_frame unless the user corrects them. If the current message provides or corrects "
            "a reservation field, put it in current_reservation_fields and ensure reservation_frame reflects "
            "the merged full state. Do not use keyword matching; infer from meaning."
        ),
        "current_message": state.message_text,
        "chat_history": [message.model_dump(mode="json") for message in state.chat_history],
        "tenant_business_info": state.tenant_context.get("business_info") or {},
        "reservation_required_fields": (state.tenant_context.get("reservation") or {}).get("required_fields") or [],
        "allowed_active_task_values": ["reservation_request"],
        "allowed_task_status_values": [
            "collecting_info",
            "blocked_by_validation",
            "ready_to_submit",
            "submitted",
            "failed",
        ],
        "supported_intents": state.profile.get("supported_intents") or [],
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
