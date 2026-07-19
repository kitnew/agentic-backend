from pydantic import BaseModel, Field

from app.agent.tools.base import BaseAgentTool
from app.capabilities.schemas import CapabilityRequest


class CreateReservationArgs(BaseModel):
    guest_name: str = Field(description="Name for the reservation.")
    date: str = Field(description="Reservation date as provided by the customer.")
    time: str = Field(description="Reservation time as provided by the customer.")
    party_size: int = Field(description="Number of guests.")
    phone: str = Field(description="Customer phone number.")
    notes: str | None = Field(default=None, description="Optional customer notes.")


class CreateReservationTool(BaseAgentTool):
    name = "create_reservation"
    capability_name = "reservation.create_request"
    description = (
        "Submit a reservation request for staff confirmation. "
        "Use only after the required reservation fields are known."
    )
    args_schema = CreateReservationArgs

    def __init__(self, capability_executor=None, raw_message: str | None = None):
        self.capability_executor = capability_executor
        self.raw_message = raw_message
        self.executions = []

    def execute(
        self,
        guest_name: str,
        date: str,
        time: str,
        party_size: int,
        phone: str,
        notes: str | None = None,
    ):
        reservation_frame = {
            "guest_name": guest_name,
            "date": date,
            "time": time,
            "party_size": party_size,
            "phone": phone,
        }
        if notes:
            reservation_frame["notes"] = notes

        if not self.capability_executor:
            return {
                "status": "success",
                "message": "Reservation request captured.",
                "reservation_frame": reservation_frame,
            }

        execution = self.capability_executor.execute(
            CapabilityRequest(
                name="reservation.create_request",
                input={
                    "raw_message": self.raw_message,
                    "reservation_frame": reservation_frame,
                },
            )
        )
        self.executions.append(execution)

        return {
            "status": execution.result.status.value,
            "message": execution.result.user_message,
            "error": execution.result.error,
            "reservation_frame": reservation_frame,
            "tool_call_id": execution.tool_call.id if execution.tool_call else None,
        }
