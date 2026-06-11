from typing import Any

from app.agent.contracts.enums import AgentTaskName, ReservationTaskStatus
from app.agent.contracts.state import AgentWorkingState
from app.capabilities.schemas import CapabilityRequest


def enabled_capabilities(state: AgentWorkingState) -> set[str]:
    capabilities = state.tenant_context.get("capabilities") or {}
    return {
        capability_name
        for capability_name, config in capabilities.items()
        if config.get("enabled")
    }


def plan_capability_requests(state: AgentWorkingState) -> list[CapabilityRequest]:
    if not reservation_submission_gate(state)["can_submit"]:
        return []
    if "reservation.create_request" not in enabled_capabilities(state):
        return []
    return [
        CapabilityRequest(
            name="reservation.create_request",
            input={
                "raw_message": state.message_text,
                "reservation_frame": state.memory.frame,
            },
            metadata={"requested_by": "agent.plan_capability"},
        )
    ]


def validate_capability_request(
    state: AgentWorkingState,
    request: CapabilityRequest,
) -> tuple[CapabilityRequest | None, dict]:
    issues = []
    if request.name not in enabled_capabilities(state):
        issues.append("capability_not_enabled")
    if request.name == "reservation.create_request" and not reservation_submission_gate(state)["can_submit"]:
        issues.append("reservation_not_ready")
    if issues:
        return None, {"ok": False, "issues": issues, "request": request.model_dump(mode="json")}
    return _with_reservation_payload(state, request), {
        "ok": True,
        "issues": [],
        "request": request.model_dump(mode="json"),
    }


def can_submit_reservation(state: AgentWorkingState) -> bool:
    return reservation_submission_gate(state)["can_submit"]


def reservation_submission_gate(state: AgentWorkingState) -> dict[str, Any]:
    blockers = []
    if state.memory.active_task != AgentTaskName.RESERVATION_REQUEST:
        blockers.append("no_active_reservation_task")
    if state.memory.task_status != ReservationTaskStatus.READY_TO_SUBMIT:
        blockers.append("task_status_not_ready")
    if state.memory.missing_fields:
        blockers.append("missing_fields")
    if state.memory.validation_errors:
        blockers.append("validation_errors")

    return {
        "can_submit": not blockers,
        "blockers": blockers,
        "active_task": state.memory.active_task.value if state.memory.active_task else None,
        "task_status": state.memory.task_status.value if state.memory.task_status else None,
        "missing_fields": state.memory.missing_fields,
        "validation_errors": [
            error.model_dump(mode="json") if hasattr(error, "model_dump") else error
            for error in state.memory.validation_errors
        ],
    }


def _with_reservation_payload(
    state: AgentWorkingState,
    request: CapabilityRequest,
) -> CapabilityRequest:
    if request.name != "reservation.create_request":
        return request
    return request.model_copy(
        update={
            "input": {
                **request.input,
                "raw_message": request.input.get("raw_message") or state.message_text,
                "reservation_frame": state.memory.frame,
            }
        }
    )
