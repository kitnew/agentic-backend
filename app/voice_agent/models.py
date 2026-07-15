import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LiveKitJobMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    call_session_id: UUID
    conversation_id: UUID
    channel: Literal["voice"]
    language: str

    @classmethod
    def parse_job(cls, raw: str) -> "LiveKitJobMetadata":
        return cls.model_validate(json.loads(raw))
