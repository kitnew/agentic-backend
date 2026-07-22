import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.agent.schemas.voice import VoiceTurnConfig


class SessionChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    content: str


class LiveKitJobMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    call_session_id: UUID
    conversation_id: UUID
    channel: Literal["voice"]
    language: str
    timezone: str
    instructions: str
    greeting: str | None = None
    enabled_capabilities: tuple[str, ...]
    reservation_request_schema: str | None = None
    chat_history: tuple[SessionChatMessage, ...] = ()
    stt_language: str
    tts_voice_id: str
    tts_model: str
    tts_language: str
    turn_config: VoiceTurnConfig

    @classmethod
    def parse_job(cls, raw: str) -> "LiveKitJobMetadata":
        return cls.model_validate(json.loads(raw))
