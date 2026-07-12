import asyncio
import base64
import json
import os
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol
from urllib.parse import urlencode

from websockets.asyncio.client import connect

from app.voice.errors import VoiceProviderConfigurationError, VoiceSTTProviderError


@dataclass(frozen=True)
class StreamingTranscriptEvent:
    text: str
    is_final: bool
    event_type: str = "partial"
    language: str | None = None
    words: list[dict] = field(default_factory=list)


class StreamingSTTSession(Protocol):
    async def send_audio(self, data: bytes) -> None: ...
    async def finalize(self) -> StreamingTranscriptEvent: ...
    async def wait_for_final(self) -> StreamingTranscriptEvent: ...
    async def close(self) -> None: ...


class StreamingSTTProvider(Protocol):
    provider_name: str
    async def open_session(self, **kwargs) -> StreamingSTTSession: ...


class ElevenLabsStreamingSTTSession:
    def __init__(self, websocket, on_event: Callable[[StreamingTranscriptEvent], Awaitable[None]]):
        self.websocket = websocket
        self.on_event = on_event
        self.final = asyncio.get_running_loop().create_future()
        self.reader = asyncio.create_task(self._read())
        self.closed = False

    async def send_audio(self, data: bytes) -> None:
        await self.websocket.send(json.dumps({
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(data).decode("ascii"),
            "commit": False,
            "sample_rate": 16000,
        }))

    async def finalize(self) -> StreamingTranscriptEvent:
        await self.websocket.send(json.dumps({
            "message_type": "input_audio_chunk", "audio_base_64": "", "commit": True,
            "sample_rate": 16000,
        }))
        return await self.final

    async def wait_for_final(self) -> StreamingTranscriptEvent:
        return await self.final

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self.websocket.close()
        if not self.reader.done():
            self.reader.cancel()
        await asyncio.gather(self.reader, return_exceptions=True)

    async def _read(self) -> None:
        try:
            async for raw in self.websocket:
                payload = json.loads(raw)
                kind = payload.get("message_type")
                if kind == "partial_transcript":
                    await self.on_event(StreamingTranscriptEvent(text=payload.get("text", ""), is_final=False))
                elif kind == "committed_transcript":
                    await self.on_event(StreamingTranscriptEvent(
                        text=payload.get("text", ""), is_final=False, event_type="speech_ended"
                    ))
                elif kind == "committed_transcript_with_timestamps":
                    event = StreamingTranscriptEvent(
                        text=payload.get("text", ""), is_final=True,
                        event_type="final", language=payload.get("language_code"), words=payload.get("words") or [],
                    )
                    if not self.final.done():
                        self.final.set_result(event)
                elif kind in {"scribe_error", "scribe_auth_error", "scribe_quota_exceeded_error"}:
                    raise VoiceSTTProviderError("Realtime STT provider failed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self.final.done():
                self.final.set_exception(
                    exc if isinstance(exc, VoiceSTTProviderError) else VoiceSTTProviderError("Realtime STT connection failed")
                )


class ElevenLabsStreamingSTTProvider:
    provider_name = "elevenlabs"

    def __init__(self, *, api_key: str | None = None, websocket_connect=connect):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        self.websocket_connect = websocket_connect

    async def open_session(
        self, *, model: str, language: str | None, keyterms: list[str],
        on_event: Callable[[StreamingTranscriptEvent], Awaitable[None]], timeout_seconds: float,
        commit_strategy: str = "manual", vad_silence_threshold_seconds: float = 1.5,
        vad_threshold: float = .4, min_speech_duration_ms: int = 100,
        min_silence_duration_ms: int = 100,
    ) -> ElevenLabsStreamingSTTSession:
        if not self.api_key:
            raise VoiceProviderConfigurationError("ELEVENLABS_API_KEY must be configured")
        query = [("model_id", model), ("audio_format", "pcm_16000"),
                 ("commit_strategy", commit_strategy), ("include_timestamps", "true"),
                 ("include_language_detection", "true")]
        if commit_strategy == "vad":
            query.extend([
                ("vad_silence_threshold_secs", str(vad_silence_threshold_seconds)),
                ("vad_threshold", str(vad_threshold)),
                ("min_speech_duration_ms", str(min_speech_duration_ms)),
                ("min_silence_duration_ms", str(min_silence_duration_ms)),
            ])
        if language:
            query.append(("language_code", language))
        query.extend(("keyterms", term) for term in keyterms)
        url = "wss://api.elevenlabs.io/v1/speech-to-text/realtime?" + urlencode(query)
        last_error = None
        for attempt in range(2):
            try:
                websocket = await asyncio.wait_for(
                    self.websocket_connect(url, additional_headers={"xi-api-key": self.api_key}),
                    timeout_seconds,
                )
                raw = await asyncio.wait_for(websocket.recv(), timeout_seconds)
                if json.loads(raw).get("message_type") != "session_started":
                    raise VoiceSTTProviderError("Realtime STT handshake failed")
                return ElevenLabsStreamingSTTSession(websocket, on_event)
            except Exception as exc:
                last_error = exc
                if attempt:
                    break
        raise VoiceSTTProviderError("Realtime STT connection failed") from last_error
