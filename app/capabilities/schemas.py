from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CapabilityStatus(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    DISABLED = "disabled"


class CapabilityExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"


class RoomAvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DATA_NOT_COVERED = "data_not_covered"


class RoomAvailabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_in: date
    check_out: date
    room_type: str
    room_count: int = Field(gt=0, strict=True)

    @field_validator("room_type")
    @classmethod
    def validate_room_type(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("room_type must not be empty")
        return value

    @model_validator(mode="after")
    def validate_stay(self):
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be later than check_in")
        return self


class RoomAvailabilityResult(BaseModel):
    status: RoomAvailabilityStatus
    room_type: str
    check_in: date
    check_out: date
    requested_rooms: int
    available_rooms: int | None


class CapabilityRequest(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] | None = None


class CapabilityResult(BaseModel):
    name: str
    status: CapabilityStatus
    output: dict[str, Any] | None = None
    user_message: str | None = None
    error: str | None = None
    provider: str


class CapabilityCommand(BaseModel):
    command_id: str
    tenant_id: str
    conversation_id: str | None = None
    call_session_id: str | None = None
    capability: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CapabilityExecutionResult(BaseModel):
    command_id: str
    status: CapabilityExecutionStatus
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    execution_duration_ms: int
    metadata: dict[str, Any] = Field(default_factory=dict)
