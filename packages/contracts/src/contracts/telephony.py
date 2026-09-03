from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PhoneAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignment_id: UUID
    tenant_id: UUID
    phone_number: str
    generation: int

