from datetime import date

from pydantic import BaseModel, Field

from app.agent.tools.base import BaseAgentTool
from app.capabilities.schemas import CapabilityRequest


class NewReservationArgs(BaseModel):
    check_in: date
    check_out: date
    reservation_name: str
    reservation_phone: str
    email: str
    room_type: str = Field(description="two_bed, three_bed, or four_bed")
    room_count: int = Field(gt=0)
    confirmed: bool = Field(description="True only after the guest confirms all final details.")


class ReservationChangeArgs(BaseModel):
    original_check_in: date
    original_check_out: date
    reservation_name: str
    reservation_phone: str
    change: str
    confirmed: bool = Field(description="True only after the guest confirms all final details.")
    check_in: date | None = None
    check_out: date | None = None
    room_type: str | None = None
    room_count: int | None = Field(default=None, gt=0)


class ReservationCancellationArgs(BaseModel):
    original_check_in: date
    original_check_out: date
    reservation_name: str
    reservation_phone: str
    confirmed: bool = Field(description="True only after the guest confirms all final details.")
    reason: str = ""


class ReservationRequestTool(BaseAgentTool):
    def __init__(self, capability_executor=None, caller_number: str | None = None, **_):
        self.capability_executor = capability_executor
        self.caller_number = caller_number
        self.executions = []

    def _execute(self, values):
        if not self.capability_executor:
            return {"status": "success", "message": "Reservation request captured."}
        execution = self.capability_executor.execute(
            CapabilityRequest(
                name=self.capability_name,
                input={**values, "caller_number": self.caller_number},
            )
        )
        self.executions.append(execution)
        return {
            "status": execution.result.status.value,
            "message": execution.result.user_message,
            "error": execution.result.error,
            "tool_call_id": execution.tool_call.id if execution.tool_call else None,
        }


class NewReservationRequestTool(ReservationRequestTool):
    name = "submit_new_reservation_request"
    capability_name = "reservation.create_request"
    description = "Submit a new accommodation request after availability and final guest confirmation."
    args_schema = NewReservationArgs

    def execute(self, **values):
        return self._execute(values)


class ReservationChangeRequestTool(ReservationRequestTool):
    name = "submit_reservation_change_request"
    capability_name = "reservation.change_request"
    description = (
        "Submit any confirmed reservation change. Include all four optional availability "
        "fields only when dates, room type, or room count changes."
    )
    args_schema = ReservationChangeArgs

    def execute(self, **values):
        return self._execute(values)


class ReservationCancellationRequestTool(ReservationRequestTool):
    name = "submit_reservation_cancellation_request"
    capability_name = "reservation.cancel_request"
    description = "Submit a reservation cancellation after final guest confirmation."
    args_schema = ReservationCancellationArgs

    def execute(self, **values):
        return self._execute(values)
