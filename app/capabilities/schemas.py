from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)


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
    requested_room_type: str
    allocated_room_type: str | None
    fallback_applied: bool
    check_in: date
    check_out: date
    requested_rooms: int
    available_rooms: int | None


class ReservationRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reservation_name: str = Field(min_length=1)
    caller_number: str | None = Field(default=None, min_length=1, strict=True)
    reservation_phone: str = Field(min_length=1, strict=True)
    confirmed: Literal[True]

    @field_validator("caller_number", "reservation_phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        digit_count = sum(character.isdigit() for character in value)
        if value.casefold() == "z volaného" or digit_count < 6:
            raise ValueError("phone number must be concrete")
        return value


class NewReservationRequest(ReservationRequestBase, RoomAvailabilityRequest):
    room_type: Literal["two_bed", "three_bed", "four_bed"]
    requested_room_type: Literal["two_bed", "three_bed", "four_bed"] | None = None


class ExistingReservationRequest(ReservationRequestBase):
    original_check_in: date
    original_check_out: date

    @model_validator(mode="after")
    def validate_original_stay(self):
        if self.original_check_out <= self.original_check_in:
            raise ValueError("original_check_out must be later than original_check_in")
        return self


class ReservationChangeRequest(ExistingReservationRequest):
    change: str = Field(min_length=1)
    check_in: date | None = None
    check_out: date | None = None
    room_type: Literal["two_bed", "three_bed", "four_bed"] | None = None
    room_count: int | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode="after")
    def validate_availability_fields(self):
        values = (self.check_in, self.check_out, self.room_type, self.room_count)
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("availability-affecting changes require all availability fields")
        if self.check_in and self.check_out and self.check_out <= self.check_in:
            raise ValueError("check_out must be later than check_in")
        return self

    @property
    def affects_availability(self) -> bool:
        return self.check_in is not None


class ReservationCancellationRequest(ExistingReservationRequest):
    reason: str = ""


class CalculatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["add", "subtract", "multiply", "divide", "percentage"]
    operands: list[Annotated[StrictStr, Field(min_length=1, max_length=128)]] = Field(
        min_length=2, max_length=10
    )

    @field_validator("operands")
    @classmethod
    def validate_operands(cls, values: list[str]) -> list[str]:
        for value in values:
            try:
                decimal = Decimal(value)
            except InvalidOperation as exc:
                raise ValueError("operands must be decimal strings") from exc
            if not decimal.is_finite():
                raise ValueError("operands must be finite decimal strings")
        return values

    @model_validator(mode="after")
    def validate_arity(self):
        if (
            self.operation in {"subtract", "divide", "percentage"}
            and len(self.operands) != 2
        ):
            raise ValueError(f"{self.operation} requires exactly two operands")
        return self


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
