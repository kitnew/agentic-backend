from typing import Any

from app.agent.contracts.enums import AgentTaskName, ReservationTaskStatus
from app.agent.contracts.state import AgentWorkingState, ResponseValidationResult
from app.agent.tasks.reservation.policy import has_value


def normalize_response_validation(
    state: AgentWorkingState,
    validation: ResponseValidationResult,
) -> dict:
    hard_issues = []
    if not state.response_text:
        hard_issues.append("empty_response")

    contract = build_response_contract(state)
    known_field_claims = [
        field_name
        for field_name in validation.asks_for_known_fields
        if field_name in contract["known_reservation_fields"]
    ]
    if validation.claims_capability_outcome and not contract["may_claim_capability_outcome"]:
        hard_issues.append("capability_outcome_claim_without_result")
    if validation.claims_task_ready and contract["task_blockers"]:
        hard_issues.append("task_ready_claim_while_blocked")
    if validation.ignores_task_blockers and contract["task_blockers"]:
        hard_issues.append("ignores_task_blockers")
    if validation.repeats_answered_questions and not contract["may_reuse_answered_facts_for_task_explanation"]:
        hard_issues.append("repeats_answered_questions")
    if known_field_claims:
        hard_issues.append("asks_for_known_fields")
    if contract["must_mention_validation_errors"] and not validation.mentions_validation_errors:
        hard_issues.append("missing_validation_error_explanation")
    if contract["must_ask_missing_fields"] and not validation.asks_for_missing_fields:
        hard_issues.append("missing_required_field_request")

    issues = [*validation.issues, *hard_issues]
    needs_revision = bool(validation.needs_revision or issues or validation.missing_requirements or validation.forbidden_content)
    return {
        "checked": True,
        "ok": not needs_revision,
        "needs_revision": needs_revision,
        "issues": issues,
        "missing_requirements": validation.missing_requirements,
        "forbidden_content": validation.forbidden_content,
        "semantic_flags": {
            "claims_capability_outcome": validation.claims_capability_outcome,
            "claims_task_ready": validation.claims_task_ready,
            "ignores_task_blockers": validation.ignores_task_blockers,
            "repeats_answered_questions": validation.repeats_answered_questions,
            "asks_for_known_fields": validation.asks_for_known_fields,
            "known_field_claims": known_field_claims,
            "mentions_validation_errors": validation.mentions_validation_errors,
            "asks_for_missing_fields": validation.asks_for_missing_fields,
            "missing_fields_asked": validation.missing_fields_asked,
        },
        "response_contract": contract,
        "notes": validation.notes,
    }


def build_response_contract(state: AgentWorkingState) -> dict[str, Any]:
    active_reservation = state.memory.active_task == AgentTaskName.RESERVATION_REQUEST
    known_reservation_fields = {
        field_name: value
        for field_name, value in state.memory.frame.items()
        if has_value(value)
    }
    task_blockers = []
    if active_reservation and state.memory.validation_errors:
        task_blockers.append("validation_errors")
    if active_reservation and state.memory.missing_fields:
        task_blockers.append("missing_fields")
    if (
        active_reservation
        and state.memory.task_status
        not in (ReservationTaskStatus.COLLECTING_INFO, ReservationTaskStatus.BLOCKED_BY_VALIDATION, ReservationTaskStatus.READY_TO_SUBMIT)
    ):
        task_blockers.append("unsupported_task_status")

    return {
        "active_reservation": active_reservation,
        "task_status": state.memory.task_status.value if state.memory.task_status else None,
        "task_blockers": task_blockers,
        "known_reservation_fields": known_reservation_fields,
        "missing_fields": state.memory.missing_fields,
        "validation_errors": [
            error.model_dump(mode="json") if hasattr(error, "model_dump") else error
            for error in state.memory.validation_errors
        ],
        "may_claim_capability_outcome": bool(state.capability_results),
        "must_not_claim_capability_outcome": not state.capability_results,
        "must_mention_validation_errors": active_reservation and bool(state.memory.validation_errors),
        "must_ask_missing_fields": active_reservation and bool(state.memory.missing_fields),
        "may_reuse_answered_facts_for_task_explanation": active_reservation and bool(state.memory.validation_errors),
    }
