import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agent.contracts.enums import AgentTaskName, ReservationTaskStatus
from app.agent.contracts.state import AgentWorkingState, TaskStateValidationResult
from app.agent.tasks.reservation.policy import (
    get_missing_fields_from_tenant,
    merge_missing_fields,
    structured_opening_hours_configured,
    validate_structured_business_rules,
)


class ValidateTaskStateNode:
    def __init__(self, llm: BaseChatModel):
        self.structured_llm = llm.with_structured_output(TaskStateValidationResult, method="function_calling")

    def __call__(self, state: AgentWorkingState) -> AgentWorkingState:
        if state.memory.active_task != AgentTaskName.RESERVATION_REQUEST:
            state.memory.missing_fields = []
            state.memory.validation_errors = []
            state.memory.task_status = None
            state.task_validation = {"ok": True, "skipped": True, "reason": "no_active_task"}
            state.trace["validate_task_state"] = state.task_validation
            return state

        try:
            llm_validation = _coerce_model(
                self.structured_llm.invoke(
                    [
                        SystemMessage(content=state.system_prompt or ""),
                        SystemMessage(content=state.tenant_prompt or ""),
                        HumanMessage(content=_validation_payload(state)),
                    ]
                ),
                TaskStateValidationResult,
            )
            error = None
        except Exception as exc:
            llm_validation = TaskStateValidationResult()
            error = str(exc)

        hard_missing_fields = get_missing_fields_from_tenant(state.memory.frame, state.tenant_context)
        missing_fields = merge_missing_fields(hard_missing_fields, llm_validation.missing_fields)
        validation_errors = _merge_validation_errors(
            llm_validation.validation_errors,
            validate_structured_business_rules(state.memory.frame, state.tenant_context),
            state.tenant_context,
        )
        task_status = _derive_task_status(missing_fields, validation_errors)

        state.memory.missing_fields = missing_fields
        state.memory.validation_errors = validation_errors
        state.memory.task_status = task_status
        state.memory.user_confirmed = state.memory.user_confirmed or llm_validation.user_confirmed
        state.task_validation = {
            "ok": not validation_errors,
            "skipped": False,
            "task_status": task_status.value,
            "missing_fields": missing_fields,
            "validation_errors": [
                error.model_dump(mode="json") if hasattr(error, "model_dump") else error
                for error in validation_errors
            ],
            "llm_validation": llm_validation.model_dump(mode="json"),
            "llm_requested_task_status": (
                llm_validation.task_status.value if llm_validation.task_status else None
            ),
            "status_source": "hard_gate",
            "error": error,
        }
        state.trace["validate_task_state"] = state.task_validation
        return state


def _validation_payload(state: AgentWorkingState) -> str:
    payload = {
        "instruction": (
            "Validate the reservation task state semantically against tenant business facts and policies. "
            "Return missing fields, business validation errors, task_status, and whether the user confirmed. "
            "Use blocked_by_validation when any collected field conflicts with tenant_business_info or "
            "tenant_policies. Specifically compare requested reservation time with opening_hours when both "
            "are available. Use collecting_info when required fields are missing. Use ready_to_submit only "
            "when every required field is present and validation_errors is empty."
        ),
        "current_message": state.message_text,
        "chat_history": [message.model_dump(mode="json") for message in state.chat_history],
        "reservation_frame": state.memory.frame,
        "reservation_required_fields": (state.tenant_context.get("reservation") or {}).get("required_fields") or [],
        "allowed_task_status_values": [
            "collecting_info",
            "blocked_by_validation",
            "ready_to_submit",
            "submitted",
            "failed",
        ],
        "tenant_business_info": state.tenant_context.get("business_info") or {},
        "structured_reservation_opening_hours": (
            (state.tenant_context.get("reservation") or {}).get("opening_hours") or []
        ),
        "tenant_policies": state.tenant_context.get("policies") or {},
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


def _derive_task_status(
    missing_fields: list[str],
    validation_errors: list[Any],
) -> ReservationTaskStatus:
    if validation_errors:
        return ReservationTaskStatus.BLOCKED_BY_VALIDATION
    if missing_fields:
        return ReservationTaskStatus.COLLECTING_INFO
    return ReservationTaskStatus.READY_TO_SUBMIT


def _merge_validation_errors(
    llm_errors: list[Any],
    structured_errors: list[Any],
    tenant_context: dict[str, Any],
) -> list[Any]:
    filtered_llm_errors = llm_errors
    if structured_opening_hours_configured(tenant_context):
        filtered_llm_errors = [
            error
            for error in llm_errors
            if not _is_time_opening_hours_error(error)
        ]

    merged = list(filtered_llm_errors)
    existing_keys = {_error_key(error) for error in merged}
    for error in structured_errors:
        key = _error_key(error)
        if key not in existing_keys:
            merged.append(error)
            existing_keys.add(key)
    return merged


def _is_time_opening_hours_error(error: Any) -> bool:
    field = getattr(error, "field", None)
    code = getattr(error, "code", None)
    if isinstance(error, dict):
        field = error.get("field")
        code = error.get("code")
    return field == "time" and code in {
        "out_of_hours",
        "outside_opening_hours",
        "outside_reservation_hours",
    }


def _error_key(error: Any) -> tuple[Any, Any]:
    if isinstance(error, dict):
        return error.get("field"), error.get("code")
    return getattr(error, "field", None), getattr(error, "code", None)
