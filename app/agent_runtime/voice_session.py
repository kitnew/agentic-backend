import base64
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.core.context import VoiceRuntimeContext
from app.voice.schemas import AudioInput, VoiceMessageRequest


class VoiceSessionClosedError(Exception):
    pass


class VoiceSessionPayloadError(Exception):
    pass


@dataclass
class VoiceSession:
    tenant_id: str
    runtime_context: VoiceRuntimeContext
    conversation_id: str | None = None
    call_session_id: str = field(default_factory=lambda: str(uuid4()))
    channel: str = "voice"
    transcript_parts: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    audio_chunks: list[bytes] = field(default_factory=list)
    audio_chunk_count: int = 0
    audio_bytes_received: int = 0
    client_event_count: int = 0
    processing: bool = False
    cancelled: bool = False
    closed: bool = False

    @property
    def language(self) -> str | None:
        return self.runtime_context.language

    @property
    def timezone(self) -> str:
        return self.runtime_context.timezone

    def session_started_event(self) -> dict[str, Any]:
        return self._event(
            "session_started",
            tenant_id=self.tenant_id,
            conversation_id=self.conversation_id,
            channel=self.channel,
            language=self.language,
            timezone=self.timezone,
        )

    def handle_audio_chunk(self, data: bytes, *, source: str) -> dict[str, Any]:
        self._ensure_open()
        self.audio_chunks.append(data)
        self.audio_chunk_count += 1
        self.audio_bytes_received += len(data)
        return self._event(
            "audio_chunk_received",
            source=source,
            chunk_index=self.audio_chunk_count,
            size_bytes=len(data),
            total_audio_bytes=self.audio_bytes_received,
            pending_audio_chunks=len(self.audio_chunks),
            pending_audio_bytes=self.pending_audio_bytes,
        )

    def handle_client_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_open()
        event_type = str(payload.get("type") or "client_event")

        if event_type == "ping":
            return self._event("pong")

        if event_type == "audio_chunk":
            audio_base64 = payload.get("audio_base64")
            if not isinstance(audio_base64, str):
                raise VoiceSessionPayloadError("audio_base64 is required")
            try:
                audio_data = base64.b64decode(audio_base64, validate=True)
            except Exception as exc:
                raise VoiceSessionPayloadError("audio_base64 must be valid base64") from exc
            return self.handle_audio_chunk(audio_data, source="base64")

        self.client_event_count += 1
        return self._event(
            "client_event_received",
            client_event_type=event_type,
            event_index=self.client_event_count,
        )

    @property
    def pending_chunk_count(self) -> int:
        return len(self.audio_chunks)

    @property
    def pending_audio_bytes(self) -> int:
        return sum(len(chunk) for chunk in self.audio_chunks)

    def build_voice_message_request(
        self,
        *,
        content_type: str,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceMessageRequest:
        self._ensure_open()
        audio_data = b"".join(self.audio_chunks)
        if not audio_data:
            raise VoiceSessionPayloadError("audio buffer is empty")

        return VoiceMessageRequest(
            tenant_id=self.tenant_id,
            conversation_id=self.conversation_id,
            channel=self.channel,
            audio=AudioInput(
                filename=filename or f"{self.call_session_id}.webm",
                content_type=content_type,
                data=audio_data,
                size_bytes=len(audio_data),
            ),
            metadata={
                "source": "websocket",
                "call_session_id": self.call_session_id,
                "audio_chunk_count": len(self.audio_chunks),
                "audio_size_bytes": len(audio_data),
                **(metadata or {}),
            },
        )

    def clear_audio_buffer(self) -> None:
        self.audio_chunks.clear()

    def processing_started_event(self) -> dict[str, Any]:
        self.processing = True
        return self._event(
            "processing_started",
            pending_audio_chunks=len(self.audio_chunks),
            pending_audio_bytes=self.pending_audio_bytes,
        )

    def finish_processing(self) -> None:
        self.processing = False

    def session_ended_event(self, *, reason: str) -> dict[str, Any]:
        self.close(cancelled=reason == "cancelled")
        return self._event(
            "session_ended",
            reason=reason,
            audio_chunks_received=self.audio_chunk_count,
            total_audio_bytes=self.audio_bytes_received,
            client_events_received=self.client_event_count,
        )

    def close(self, *, cancelled: bool = False) -> None:
        self.cancelled = self.cancelled or cancelled
        self.closed = True

    def error_event(self, message: str, *, code: str = "bad_request") -> dict[str, Any]:
        return self._event("error", code=code, message=message)

    def _ensure_open(self) -> None:
        if self.closed:
            raise VoiceSessionClosedError("Voice session is closed")

    def _event(self, event_type: str, **payload: Any) -> dict[str, Any]:
        return {
            "type": event_type,
            "call_session_id": self.call_session_id,
            **payload,
        }
