import asyncio
import base64
import json
import os
from urllib.parse import urlencode

import requests
import websockets

from app.tenants.schemas import TenantVoiceTTSConfig
from app.voice.errors import VoiceProviderConfigurationError, VoiceTTSProviderError
from app.voice.schemas import SynthesizedAudioResult


class ElevenLabsTTSProvider:
    provider_name = "elevenlabs"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.elevenlabs.io/v1",
        timeout_seconds: int = 120,
    ):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def synthesize(
        self,
        text: str,
        *,
        config: TenantVoiceTTSConfig,
    ) -> SynthesizedAudioResult:
        if not self.api_key:
            raise VoiceProviderConfigurationError("ELEVENLABS_API_KEY must be configured")

        voice_id = config.voice_id or os.getenv("ELEVENLABS_VOICE_ID")
        if not voice_id:
            raise VoiceProviderConfigurationError(
                "voice.tts.voice_id or ELEVENLABS_VOICE_ID must be configured"
            )

        payload = {
            "text": text,
            "model_id": config.model,
        }
        if config.language:
            payload["language_code"] = config.language

        try:
            response = requests.post(
                f"{self.base_url}/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                params={"output_format": config.output_format},
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise VoiceTTSProviderError("TTS provider request failed") from exc

        if response.status_code >= 400:
            raise VoiceTTSProviderError(
                f"TTS provider request failed with status {response.status_code}"
            )

        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        if not content_type:
            content_type = self._content_type_from_output_format(config.output_format)

        audio_bytes = response.content
        if not audio_bytes:
            raise VoiceTTSProviderError("TTS provider returned empty audio")

        return SynthesizedAudioResult(
            provider=self.provider_name,
            content_type=content_type,
            size_bytes=len(audio_bytes),
            audio_bytes=audio_bytes,
            metadata={
                "model": config.model,
                "voice_id": voice_id,
                "output_format": config.output_format,
                "request_id": response.headers.get("request-id")
                or response.headers.get("x-request-id"),
            },
        )

    async def stream_input(self, fragments, *, config: TenantVoiceTTSConfig):
        if not self.api_key:
            raise VoiceProviderConfigurationError("ELEVENLABS_API_KEY must be configured")
        voice_id = config.voice_id or os.getenv("ELEVENLABS_VOICE_ID")
        if not voice_id:
            raise VoiceProviderConfigurationError(
                "voice.tts.voice_id or ELEVENLABS_VOICE_ID must be configured"
            )
        ws_base = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        query = urlencode({"model_id": config.model, "output_format": "pcm_24000", "auto_mode": "true"})
        if config.language:
            query += "&" + urlencode({"language_code": config.language})
        uri = f"{ws_base}/text-to-speech/{voice_id}/stream-input?{query}"
        async with websockets.connect(
            uri, additional_headers={"xi-api-key": self.api_key}, open_timeout=self.timeout_seconds
        ) as socket:
            await socket.send(json.dumps({"text": " "}))

            async def send_text():
                async for fragment in fragments:
                    await socket.send(json.dumps({"text": fragment, "flush": True}))
                await socket.send(json.dumps({"text": ""}))

            sender = asyncio.create_task(send_text())
            try:
                async for raw in socket:
                    message = json.loads(raw)
                    if message.get("audio"):
                        yield base64.b64decode(message["audio"])
                    if message.get("isFinal"):
                        break
                await sender
            finally:
                if not sender.done():
                    sender.cancel()

    def _content_type_from_output_format(self, output_format: str) -> str:
        if output_format.startswith("mp3"):
            return "audio/mpeg"
        if output_format.startswith("wav"):
            return "audio/wav"
        if output_format.startswith("pcm"):
            return "audio/L16"
        if output_format.startswith("ulaw"):
            return "audio/basic"
        return "application/octet-stream"
