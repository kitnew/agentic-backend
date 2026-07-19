from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.tools.base import BaseAgentTool
from app.capabilities.schemas import CapabilityRequest


class CheckRoomAvailabilityArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_in: date = Field(description="Check-in date in YYYY-MM-DD format.")
    check_out: date = Field(description="Check-out date in YYYY-MM-DD format.")
    room_type: str = Field(
        description="Tenant room type code, such as two_bed, three_bed, or four_bed."
    )
    room_count: int = Field(gt=0, strict=True, description="Number of rooms requested.")

    @model_validator(mode="after")
    def validate_stay(self):
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be later than check_in")
        return self


class CheckRoomAvailabilityTool(BaseAgentTool):
    name = "check_room_availability"
    capability_name = "reservation.check_availability"
    description = (
        "Check whether a number of rooms of one tenant room type is continuously free "
        "for every night from check-in (inclusive) to check-out (exclusive). "
        "Check-in must be today or later; check-out is the departure date. "
        "This is a read-only snapshot and does not reserve or hold rooms."
    )
    args_schema = CheckRoomAvailabilityArgs

    def __init__(self, capability_executor=None, **_kwargs):
        self.capability_executor = capability_executor
        self.executions = []

    def execute(
        self,
        check_in: date,
        check_out: date,
        room_type: str,
        room_count: int,
    ):
        if not self.capability_executor:
            return {
                "status": "failed",
                "message": "Availability execution is not configured.",
            }

        execution = self.capability_executor.execute(
            CapabilityRequest(
                name=self.capability_name,
                input={
                    "check_in": check_in.isoformat(),
                    "check_out": check_out.isoformat(),
                    "room_type": room_type,
                    "room_count": room_count,
                },
            )
        )
        self.executions.append(execution)
        return {
            "status": execution.result.status.value,
            "message": execution.result.user_message,
            "error": execution.result.error,
            "result": execution.result.output,
            "tool_call_id": execution.tool_call.id if execution.tool_call else None,
        }
