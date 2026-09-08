from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.execution import WorkerExecutionContext

_DECIMAL_PATTERN = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$"
)


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CapabilityInvocationStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


class CalculatorRequest(_Contract):
    operation: Literal["add", "subtract", "multiply", "divide", "percentage"]
    operands: list[str] = Field(min_length=2, max_length=10)

    @field_validator("operands")
    @classmethod
    def validate_decimal_operands(cls, values: list[str]) -> list[str]:
        for value in values:
            if not _DECIMAL_PATTERN.fullmatch(value):
                raise ValueError("operands must be decimal values")
            try:
                decimal = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError("operands must be decimal values") from exc
            if not decimal.is_finite():
                raise ValueError("operands must be finite decimal values")
        return values

    @model_validator(mode="after")
    def validate_operand_count(self) -> CalculatorRequest:
        required = 2 if self.operation in {"subtract", "divide", "percentage"} else None
        if required is not None and len(self.operands) != required:
            raise ValueError(f"{self.operation} requires exactly 2 operands")
        return self


class TraceContext(_Contract):
    correlation_id: str | None = Field(default=None, max_length=255)
    traceparent: str | None = Field(default=None, max_length=255)


class IntegrationJob(_Contract):
    job_version: Literal[4] = 4
    job_id: UUID
    job_type: Literal["integration.execute"] = "integration.execute"
    capability_invocation_id: UUID
    call_id: UUID | None = None
    execution_id: UUID
    worker_context: WorkerExecutionContext
    tool_args: dict[str, object]
    metadata: dict[str, object] = Field(default_factory=dict)
    confirmed: bool = False
    attempt: int = Field(default=1, ge=1, le=10)
    created_at: datetime
    expires_at: datetime
    trace_context: TraceContext = Field(default_factory=TraceContext)

    @model_validator(mode="after")
    def expiration_follows_creation(self) -> IntegrationJob:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self


class HttpRequestResult(_Contract):
    result_type: Literal["http.request.v1"]
    status: Literal["succeeded"]
    operation_id: UUID
    reference: str | None = Field(default=None, max_length=1024)
    deduplicated: bool = False
    data: object | None = None


TechnicalResult = HttpRequestResult


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


class CapabilityConfirmationConfirmRequest(_Contract):
    tool_call_id: str = Field(min_length=1, max_length=255)


class CapabilityConfirmationResponse(_Contract):
    id: UUID
    status: Literal["confirmation_required"] = "confirmation_required"
    summary: dict[str, object]
    expires_at: datetime


class CapabilityInvocationResponse(_Contract):
    id: UUID
    call_id: UUID
    semantic_key: str
    status: CapabilityInvocationStatus
    semantic_result: dict[str, object] | str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
