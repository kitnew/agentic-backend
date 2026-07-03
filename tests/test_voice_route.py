import asyncio

from fastapi import FastAPI, HTTPException

from app.api.routes.voice import receive_voice_message, router
from app.voice.schemas import SynthesizedAudioResult, TranscriptResult, VoiceMessageResponse


class FakeVoiceMessageService:
    def __init__(self):
        self.requests = []

    def process(self, request):
        self.requests.append(request)
        return VoiceMessageResponse(
            conversation_id=request.conversation_id or "conversation-1",
            transcript="Chcem rezervaciu",
            response_text="Na kedy?",
            audio_url="/api/v1/voice/audio/test.mp3",
            transcript_result=TranscriptResult(
                provider="fake_stt",
                text="Chcem rezervaciu",
                language="sk",
                audio_duration_ms=1000,
            ),
            audio=SynthesizedAudioResult(
                provider="fake_tts",
                content_type="audio/mpeg",
                size_bytes=10,
                audio_url="/api/v1/voice/audio/test.mp3",
            ),
            metadata={
                "stt_provider": "fake_stt",
                "tts_provider": "fake_tts",
                "language": "sk",
                "audio_duration_ms": 1000,
                "content_type": "audio/webm",
                "warnings": [],
            },
        )


class FakeUploadFile:
    def __init__(
        self,
        data: bytes = b"audio",
        *,
        filename: str = "message.webm",
        content_type: str = "audio/webm",
    ):
        self.data = data
        self.filename = filename
        self.content_type = content_type

    async def read(self) -> bytes:
        return self.data


def test_voice_messages_handler_accepts_multipart_parts():
    service = FakeVoiceMessageService()

    response = asyncio.run(
        receive_voice_message(
            tenant_id=" tenant-1 ",
            channel="browser",
            external_user_id="user-1",
            metadata='{"source":"route-test"}',
            audio_file=FakeUploadFile(),
            service=service,
        )
    )
    voice_request = service.requests[0]

    assert response.conversation_id == "conversation-1"
    assert response.transcript == "Chcem rezervaciu"
    assert response.audio_url == "/api/v1/voice/audio/test.mp3"
    assert voice_request.tenant_id == "tenant-1"
    assert voice_request.channel == "browser"
    assert voice_request.external_user_id == "user-1"
    assert voice_request.audio.filename == "message.webm"
    assert voice_request.audio.content_type == "audio/webm"
    assert voice_request.audio.data == b"audio"
    assert voice_request.metadata == {"source": "route-test"}


def test_voice_messages_handler_rejects_invalid_metadata_json():
    service = FakeVoiceMessageService()

    try:
        asyncio.run(
            receive_voice_message(
                tenant_id="tenant-1",
                channel="browser",
                metadata="{broken",
                audio_file=FakeUploadFile(),
                service=service,
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "metadata must be valid JSON"
        assert service.requests == []
        return

    raise AssertionError("expected HTTPException")


def test_voice_messages_route_declares_multipart_request_body():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/voice")

    operation = app.openapi()["paths"]["/api/v1/voice/messages"]["post"]
    content = operation["requestBody"]["content"]
    schema_ref = content["multipart/form-data"]["schema"]["$ref"]
    schema_name = schema_ref.rsplit("/", 1)[-1]
    schema = app.openapi()["components"]["schemas"][schema_name]

    assert operation["requestBody"]["required"] is True
    assert schema["required"] == ["tenant_id", "channel", "audio_file"]
    assert schema["properties"]["audio_file"]["format"] == "binary"
