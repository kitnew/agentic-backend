from enum import Enum
from typing import Any


class AgendaItemType(str, Enum):
    QUESTION = "question"
    TASK = "task"
    INFO = "info"


class AgentTaskName(str, Enum):
    RESERVATION_REQUEST = "reservation_request"


class ReservationTaskStatus(str, Enum):
    COLLECTING_INFO = "collecting_info"
    BLOCKED_BY_VALIDATION = "blocked_by_validation"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTED = "submitted"
    FAILED = "failed"


class ResponseMode(str, Enum):
    DIRECT = "direct"
    AFTER_CAPABILITY = "after_capability"


def normalize_agent_task_name(value: Any) -> AgentTaskName | None:
    if value is None or value == "":
        return None
    if isinstance(value, AgentTaskName):
        return value
    try:
        return AgentTaskName(value)
    except ValueError:
        return None


def normalize_reservation_task_status(value: Any) -> ReservationTaskStatus | None:
    if value is None or value == "":
        return None
    if isinstance(value, ReservationTaskStatus):
        return value
    try:
        return ReservationTaskStatus(value)
    except ValueError:
        return None
