from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

JsonScalar = str | int | float | bool | None


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CapabilityInvocationStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


class RuntimeCapabilityDefinition(_Contract):
    semantic_key: str
    semantic_version: int = Field(gt=0)
    tool_name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    description: str = Field(min_length=1, max_length=1000)
    announcement: str = Field(min_length=1, max_length=1000)
    input_schema: dict[str, object]


class GoogleSheetsIdempotency(_Contract):
    operation_id: UUID
    lookup_range: str = Field(min_length=1, max_length=255)
    operation_id_column_index: int = Field(ge=0, le=1023)


class GoogleSheetsAppendValuesPlan(_Contract):
    plan_type: Literal["google_sheets.append_values.v1"]
    mapping_language: Literal["jsonata"] = "jsonata"
    mapping_contract_version: Literal[1] = 1
    mapping_engine: Literal["jsonata-python"] = "jsonata-python"
    mapping_engine_version: Literal["0.7.0"] = "0.7.0"
    credential_ref: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    spreadsheet_id: str = Field(min_length=1, max_length=255)
    sheet_name: str = Field(min_length=1, max_length=255)
    append_range: str = Field(min_length=1, max_length=255)
    value_input_option: Literal["RAW", "USER_ENTERED"]
    rows: list[list[JsonScalar]] = Field(min_length=1, max_length=100)
    idempotency: GoogleSheetsIdempotency


ExecutionPlan = Annotated[
    GoogleSheetsAppendValuesPlan,
    Field(discriminator="plan_type"),
]


class TraceContext(_Contract):
    correlation_id: str | None = Field(default=None, max_length=255)
    traceparent: str | None = Field(default=None, max_length=255)


class IntegrationJob(_Contract):
    job_version: Literal[1] = 1
    job_id: UUID
    job_type: Literal["integration.execute"] = "integration.execute"
    capability_invocation_id: UUID
    tenant_id: UUID
    execution_plan: ExecutionPlan
    attempt: int = Field(default=1, ge=1, le=10)
    created_at: datetime
    expires_at: datetime
    trace_context: TraceContext = Field(default_factory=TraceContext)

    @model_validator(mode="after")
    def expiration_follows_creation(self) -> IntegrationJob:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self


class GoogleSheetsAppendValuesResult(_Contract):
    result_type: Literal["google_sheets.append_values.v1"]
    status: Literal["succeeded"]
    updated_range: str = Field(min_length=1, max_length=1024)
    updated_rows: int = Field(ge=1)
    deduplicated: bool


TechnicalResult = Annotated[
    GoogleSheetsAppendValuesResult,
    Field(discriminator="result_type"),
]


class WorkerError(_Contract):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1000)
    transient: bool


class WorkerResultReport(_Contract):
    job_id: UUID
    capability_invocation_id: UUID
    status: Literal["succeeded", "failed"]
    result: TechnicalResult | None = None
    error: WorkerError | None = None
    attempt: int = Field(ge=1, le=10)
    started_at: datetime
    completed_at: datetime
    provider_reference: str | None = Field(default=None, max_length=1024)
    trace_context: TraceContext = Field(default_factory=TraceContext)

    @model_validator(mode="after")
    def exactly_one_outcome(self) -> WorkerResultReport:
        if self.status == "succeeded" and (
            self.result is None or self.error is not None
        ):
            raise ValueError("successful reports require only result")
        if self.status == "failed" and (self.error is None or self.result is not None):
            raise ValueError("failed reports require only error")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        return self


class CapabilityInvocationRequest(_Contract):
    tool_call_id: str = Field(min_length=1, max_length=255)
    capability: str = Field(min_length=1, max_length=128)
    agent_input: dict[str, object]


class ReservationRequestSubmitted(_Contract):
    status: Literal["request_submitted"] = "request_submitted"
    request_reference: str | None = Field(default=None, max_length=1024)
    deduplicated: bool


class CapabilityInvocationResponse(_Contract):
    id: UUID
    call_id: UUID
    semantic_key: str
    semantic_version: int
    status: CapabilityInvocationStatus
    semantic_result: ReservationRequestSubmitted | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
