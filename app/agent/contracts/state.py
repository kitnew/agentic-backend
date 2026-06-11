from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.contracts.enums import (
    AgendaItemType,
    AgentTaskName,
    ReservationTaskStatus,
    ResponseMode,
    normalize_agent_task_name,
    normalize_reservation_task_status,
)
from app.capabilities.schemas import CapabilityRequest, CapabilityResult


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    content: str
    created_at: str | None = None
    metadata: dict[str, Any] | None = None


class AgendaItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: AgendaItemType
    name: str
    status: str = "needs_answer"
    text: str | None = None


class TaskValidationError(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str | None = None
    code: str | None = None
    message: str = ""


class ReservationMemory(BaseModel):
    frame: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    validation_errors: list[TaskValidationError] = Field(default_factory=list)
    active_task: AgentTaskName | None = None
    task_status: ReservationTaskStatus | None = None
    asked_fields: list[str] = Field(default_factory=list)
    field_attempt_count: dict[str, int] = Field(default_factory=dict)
    user_confirmed: bool = False

    @field_validator("active_task", mode="before")
    @classmethod
    def _normalize_active_task(cls, value: Any) -> AgentTaskName | None:
        return normalize_agent_task_name(value)

    @field_validator("task_status", mode="before")
    @classmethod
    def _normalize_task_status(cls, value: Any) -> ReservationTaskStatus | None:
        return normalize_reservation_task_status(value)


class AgentDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary_intent: str = "unknown"
    detected_intents: list[str] = Field(default_factory=list)
    agenda_items: list[AgendaItem] = Field(default_factory=list)
    active_task: AgentTaskName | None = None
    task_status: ReservationTaskStatus | None = None
    requested_capabilities: list[CapabilityRequest] = Field(default_factory=list)
    response_notes: list[str] = Field(default_factory=list)

    @field_validator("active_task", mode="before")
    @classmethod
    def _normalize_active_task(cls, value: Any) -> AgentTaskName | None:
        return normalize_agent_task_name(value)

    @field_validator("task_status", mode="before")
    @classmethod
    def _normalize_task_status(cls, value: Any) -> ReservationTaskStatus | None:
        return normalize_reservation_task_status(value)


class ChatMemoryExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answered_questions: list[str] = Field(default_factory=list)
    current_question_intents: list[str] = Field(default_factory=list)
    active_task: AgentTaskName | None = None
    task_status: ReservationTaskStatus | None = None
    reservation_frame: dict[str, Any] = Field(default_factory=dict)
    current_reservation_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    validation_errors: list[TaskValidationError] = Field(default_factory=list)
    asked_fields: list[str] = Field(default_factory=list)
    field_attempt_count: dict[str, int] = Field(default_factory=dict)
    user_confirmed: bool = False
    notes: list[str] = Field(default_factory=list)

    @field_validator("active_task", mode="before")
    @classmethod
    def _normalize_active_task(cls, value: Any) -> AgentTaskName | None:
        return normalize_agent_task_name(value)

    @field_validator("task_status", mode="before")
    @classmethod
    def _normalize_task_status(cls, value: Any) -> ReservationTaskStatus | None:
        return normalize_reservation_task_status(value)


class ReservationExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field_updates: dict[str, Any] = Field(default_factory=dict)
    corrected_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    validation_errors: list[TaskValidationError] = Field(default_factory=list)
    active_task: AgentTaskName | None = None
    task_status: ReservationTaskStatus | None = None
    user_confirmed: bool = False
    notes: list[str] = Field(default_factory=list)

    @field_validator("active_task", mode="before")
    @classmethod
    def _normalize_active_task(cls, value: Any) -> AgentTaskName | None:
        return normalize_agent_task_name(value)

    @field_validator("task_status", mode="before")
    @classmethod
    def _normalize_task_status(cls, value: Any) -> ReservationTaskStatus | None:
        return normalize_reservation_task_status(value)


class TaskStateValidationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_status: ReservationTaskStatus | None = None
    missing_fields: list[str] = Field(default_factory=list)
    validation_errors: list[TaskValidationError] = Field(default_factory=list)
    user_confirmed: bool = False
    notes: list[str] = Field(default_factory=list)

    @field_validator("task_status", mode="before")
    @classmethod
    def _normalize_task_status(cls, value: Any) -> ReservationTaskStatus | None:
        return normalize_reservation_task_status(value)


class ResponseDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    response_text: str | None = None


class ResponseValidationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool = True
    needs_revision: bool = False
    issues: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    forbidden_content: list[str] = Field(default_factory=list)
    claims_capability_outcome: bool = False
    claims_task_ready: bool = False
    ignores_task_blockers: bool = False
    repeats_answered_questions: bool = False
    asks_for_known_fields: list[str] = Field(default_factory=list)
    mentions_validation_errors: bool = False
    asks_for_missing_fields: bool = False
    missing_fields_asked: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_missing_field_flags(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        asks_for_missing_fields = value.get("asks_for_missing_fields")
        if isinstance(asks_for_missing_fields, list):
            value = {
                **value,
                "asks_for_missing_fields": bool(asks_for_missing_fields),
                "missing_fields_asked": value.get("missing_fields_asked") or asks_for_missing_fields,
            }
        return value


class AgentWorkingState(BaseModel):
    tenant_id: str
    conversation_id: str | None = None
    message_id: str | None = None
    channel: str | None = None
    message_text: str
    tenant_context: dict[str, Any]
    tenant_agent: dict[str, Any]
    profile: dict[str, Any]
    chat_history: list[ChatMessage] = Field(default_factory=list)
    system_prompt: str | None = None
    tenant_prompt: str | None = None

    answered_questions: list[str] = Field(default_factory=list)
    current_question_intents: list[str] = Field(default_factory=list)
    current_reservation_fields: dict[str, Any] = Field(default_factory=dict)
    memory: ReservationMemory = Field(default_factory=ReservationMemory)
    decision: AgentDecision = Field(default_factory=AgentDecision)

    decision_feedback: list[str] = Field(default_factory=list)
    decision_validation: dict[str, Any] = Field(default_factory=dict)
    task_validation: dict[str, Any] = Field(default_factory=dict)
    capability_validation: dict[str, Any] = Field(default_factory=dict)
    response_validation: dict[str, Any] = Field(default_factory=dict)

    requested_capabilities: list[CapabilityRequest] = Field(default_factory=list)
    capability_results: list[CapabilityResult] = Field(default_factory=list)
    tool_calls: list[Any] = Field(default_factory=list)

    response_text: str | None = None
    response_mode: ResponseMode = ResponseMode.DIRECT
    trace: dict[str, Any] = Field(default_factory=dict)


class GraphState(TypedDict, total=False):
    agent_input: Any
    state: AgentWorkingState
    result: Any
    decision_iteration: int
    response_iteration: int
