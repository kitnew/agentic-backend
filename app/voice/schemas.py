from typing import Any

from pydantic import BaseModel, Field


class AudioInput(BaseModel):
    filename: str | None = None
    content_type: str | None = None
    data: bytes
    size_bytes: int


class VoiceMessageRequest(BaseModel):
    tenant_id: str
    channel: str
    audio: AudioInput
    external_user_id: str | None = None
    conversation_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinalizedTranscriptRequest(BaseModel):
    tenant_id: str
    transcript: str
    provider: str
    model: str
    language: str | None = None
    conversation_id: str | None = None
    external_user_id: str | None = None
    channel: str = "voice"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranscriptResult(BaseModel):
    provider: str
    text: str
    language: str | None = None
    audio_duration_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SynthesizedAudioResult(BaseModel):
    provider: str
    content_type: str
    size_bytes: int
    audio_url: str | None = None
    audio_base64: str | None = None
    audio_bytes: bytes | None = Field(default=None, exclude=True)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceMessageResponse(BaseModel):
    conversation_id: str
    transcript: str
    response_text: str | None = None
    audio_url: str | None = None
    audio_base64: str | None = None
    transcript_result: TranscriptResult
    audio: SynthesizedAudioResult | None = None
    agent_trace: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
