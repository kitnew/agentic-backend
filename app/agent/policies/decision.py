from typing import Any

from app.agent.contracts.enums import AgentTaskName
from app.agent.contracts.state import AgendaItem, AgentDecision, AgentWorkingState


SUPPORTED_DEFAULT_INTENTS = {
    "reservation_request",
    "opening_hours",
    "parking_question",
    "menu_question",
    "contact_request",
    "human_handoff",
    "complaint",
    "unknown",
}
QUESTION_INTENTS = {
    "opening_hours",
    "parking_question",
    "menu_question",
    "contact_request",
    "human_handoff",
    "complaint",
}


def validate_decision(
    state: AgentWorkingState,
    raw_decision: AgentDecision,
    *,
    iteration: int,
    max_iterations: int,
) -> tuple[AgentDecision, dict[str, Any]]:
    supported = set(state.profile.get("supported_intents") or SUPPORTED_DEFAULT_INTENTS)
    issues = []
    rejected_intents = []
    detected_intents = []

    for intent in raw_decision.detected_intents or [raw_decision.primary_intent]:
        if intent in supported and intent not in detected_intents:
            detected_intents.append(intent)
        elif intent and intent not in supported and intent not in rejected_intents:
            rejected_intents.append(intent)

    if rejected_intents:
        issues.append("unsupported_intent")

    for question_intent in state.current_question_intents:
        if question_intent in supported and question_intent not in detected_intents:
            detected_intents.append(question_intent)

    reservation_allowed = state.memory.active_task == AgentTaskName.RESERVATION_REQUEST
    if "reservation_request" in detected_intents and not reservation_allowed:
        detected_intents.remove("reservation_request")
        issues.append("unsolicited_reservation_task")

    if reservation_allowed and "reservation_request" not in detected_intents:
        detected_intents = ["reservation_request", *[i for i in detected_intents if i != "unknown"]]

    detected_intents = _drop_unknown_when_specific(_merge_unique(detected_intents))
    if not detected_intents:
        detected_intents = ["unknown"]

    current_questions = set(state.current_question_intents)
    agenda_items = []
    for item in raw_decision.agenda_items:
        if item.type == "question" and item.name not in current_questions:
            if item.name in state.answered_questions:
                issues.append(f"already_answered_question:{item.name}")
            continue
        if item.type == "task" and item.name == "reservation_request" and not reservation_allowed:
            issues.append("unsolicited_reservation_task")
            continue
        agenda_items.append(item)

    for intent in detected_intents:
        if intent in QUESTION_INTENTS and intent in current_questions:
            agenda_items.append(AgendaItem(type="question", name=intent, status="needs_answer"))
        if intent == AgentTaskName.RESERVATION_REQUEST.value:
            agenda_items.append(
                AgendaItem(
                    type="task",
                    name=AgentTaskName.RESERVATION_REQUEST.value,
                    status=state.memory.task_status.value if state.memory.task_status else "collecting_info",
                )
            )

    agenda_items = _merge_agenda_items(agenda_items)
    active_task = AgentTaskName.RESERVATION_REQUEST if "reservation_request" in detected_intents else None
    if state.memory.active_task == AgentTaskName.RESERVATION_REQUEST:
        active_task = AgentTaskName.RESERVATION_REQUEST

    sanitized = raw_decision.model_copy(
        update={
            "primary_intent": _primary_intent(detected_intents),
            "detected_intents": detected_intents,
            "agenda_items": agenda_items,
            "active_task": active_task,
            "task_status": raw_decision.task_status or state.memory.task_status,
        }
    )
    retry = bool(issues and iteration < max_iterations)
    return sanitized, {
        "ok": not issues,
        "retry": retry,
        "issues": issues,
        "rejected_intents": rejected_intents,
        "reservation_allowed": reservation_allowed,
    }


def _primary_intent(intents: list[str]) -> str:
    if "reservation_request" in intents:
        return "reservation_request"
    for intent in intents:
        if intent != "unknown":
            return intent
    return "unknown"


def _merge_unique(values: list[str]) -> list[str]:
    merged = []
    for value in values:
        if value and value not in merged:
            merged.append(value)
    return merged


def _drop_unknown_when_specific(intents: list[str]) -> list[str]:
    if len(intents) > 1:
        return [intent for intent in intents if intent != "unknown"]
    return intents


def _merge_agenda_items(items: list[AgendaItem]) -> list[AgendaItem]:
    order = {"question": 0, "task": 1, "info": 2}
    merged = []
    seen = set()
    for item in sorted(items, key=lambda item: order.get(item.type, 99)):
        key = (item.type, item.name)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged
