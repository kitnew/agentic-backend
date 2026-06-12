from datetime import datetime

from app.schemas.messages import MessageResponse, ProcessMessageResponse
from app.tenants.schemas import TenantContext
from app.voice.audio.validation import validate_audio_input
from app.voice.errors import VoiceDisabledError, VoiceTTSProviderError, VoiceValidationError
from app.voice.schemas import AudioInput, SynthesizedAudioResult, TranscriptResult, VoiceMessageRequest
from app.voice.service import VoiceMessageService


class FakeTenantConfigLoader:
    def __init__(self, tenant_context: TenantContext):
        self.tenant_context = tenant_context

    def load(self, tenant_id: str) -> TenantContext:
        assert tenant_id == self.tenant_context.tenant_id
        return self.tenant_context


class FakeMessageProcessor:
    def __init__(self, response_text: str = "Agent text response"):
        self.response_text = response_text
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        now = datetime.now()
        user_message = MessageResponse(
            id="user-message-1",
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id or "conversation-1",
            channel=request.channel,
            external_user_id=request.external_user_id,
            role="user",
            content=request.content,
            status="processed",
            metadata=request.metadata,
            created_at=now,
            processed_at=now,
        )
        assistant_message = MessageResponse(
            id="assistant-message-1",
            tenant_id=request.tenant_id,
            conversation_id=user_message.conversation_id,
            channel=request.channel,
            external_user_id=request.external_user_id,
            role="assistant",
            content=self.response_text,
            status="processed",
            metadata={},
            created_at=now,
            processed_at=now,
        )
        return ProcessMessageResponse(
            conversation_id=user_message.conversation_id,
            user_message=user_message,
            assistant_message=assistant_message,
            response_text=self.response_text,
            requested_capabilities=[],
            capability_results=[],
            tool_calls=[],
            agent_trace={},
            status="processed",
        )


class FakeSTTProvider:
    provider_name = "fake_stt"

    def __init__(self, text: str = "Chcem rezervaciu"):
        self.text = text
        self.calls = []

    def transcribe(self, audio, *, config):
        self.calls.append((audio, config))
        return TranscriptResult(
            provider=self.provider_name,
            text=self.text,
            language=config.language,
            audio_duration_ms=1200,
            metadata={"model": config.model},
        )


class FakeTTSProvider:
    provider_name = "fake_tts"

    def __init__(self):
        self.calls = []

    def synthesize(self, text, *, config):
        self.calls.append((text, config))
        return SynthesizedAudioResult(
            provider=self.provider_name,
            content_type="audio/mpeg",
            size_bytes=10,
            audio_bytes=b"audio-data",
            metadata={"model": config.model},
        )


class FailingTTSProvider:
    provider_name = "fake_tts"

    def synthesize(self, text, *, config):
        raise VoiceTTSProviderError("TTS provider request failed")


class FakeAudioStorage:
    def __init__(self):
        self.saved = []

    def save(self, *, tenant_id, conversation_id, audio):
        self.saved.append((tenant_id, conversation_id, audio))
        return audio.model_copy(
            update={
                "audio_url": f"/voice/audio/{conversation_id}.mp3",
                "audio_bytes": None,
            }
        )


def build_tenant_context(*, voice_enabled: bool = True, fallback_tts: bool = True) -> TenantContext:
    return TenantContext.model_validate(
        {
            "tenant_id": "tenant-1",
            "name": "Tenant",
            "business_type": "restaurant",
            "default_language": "sk",
            "locale": "sk-SK",
            "timezone": "Europe/Bratislava",
            "agent": {"profile": "restaurant_assistant"},
            "voice": {
                "enabled": voice_enabled,
                "stt": {
                    "provider": "fake_stt",
                    "model": "fake-stt-model",
                    "language": "sk",
                    "keyterms": ["rezervacia"],
                },
                "tts": {
                    "provider": "fake_tts",
                    "model": "fake-tts-model",
                    "voice_id": "voice-1",
                    "output_format": "mp3_44100_128",
                    "language": "sk",
                },
                "fallback": {
                    "send_text_if_tts_fails": fallback_tts,
                    "continue_if_stt_metadata_missing": True,
                },
            },
        }
    )


def build_request(audio: AudioInput | None = None) -> VoiceMessageRequest:
    return VoiceMessageRequest(
        tenant_id="tenant-1",
        conversation_id=None,
        channel="browser",
        external_user_id="user-1",
        audio=audio
        or AudioInput(
            filename="message.webm",
            content_type="audio/webm",
            data=b"audio",
            size_bytes=5,
        ),
        metadata={"source": "test"},
    )


def build_service(
    tenant_context: TenantContext,
    *,
    stt_provider=None,
    tts_provider=None,
    message_processor=None,
    audio_storage=None,
) -> VoiceMessageService:
    return VoiceMessageService(
        tenant_config_loader=FakeTenantConfigLoader(tenant_context),
        message_processor=message_processor or FakeMessageProcessor(),
        stt_providers={"fake_stt": stt_provider or FakeSTTProvider()},
        tts_providers={"fake_tts": tts_provider or FakeTTSProvider()},
        audio_storage=audio_storage or FakeAudioStorage(),
    )


def test_voice_disabled_tenant_rejects_request():
    service = build_service(build_tenant_context(voice_enabled=False))

    try:
        service.process(build_request())
    except VoiceDisabledError as exc:
        assert "disabled" in exc.public_message
        return

    raise AssertionError("expected VoiceDisabledError")


def test_voice_disabled_tenant_does_not_build_message_processor():
    def fail_if_called():
        raise AssertionError("message processor should not be created for disabled voice")

    service = VoiceMessageService(
        tenant_config_loader=FakeTenantConfigLoader(build_tenant_context(voice_enabled=False)),
        message_processor_factory=fail_if_called,
        stt_providers={"fake_stt": FakeSTTProvider()},
        tts_providers={"fake_tts": FakeTTSProvider()},
        audio_storage=FakeAudioStorage(),
    )

    try:
        service.process(build_request())
    except VoiceDisabledError:
        return

    raise AssertionError("expected VoiceDisabledError")


def test_invalid_or_missing_audio_file_is_rejected():
    config = build_tenant_context().voice

    for audio in [
        None,
        AudioInput(filename="empty.webm", content_type="audio/webm", data=b"", size_bytes=0),
        AudioInput(filename="text.txt", content_type="text/plain", data=b"text", size_bytes=4),
    ]:
        try:
            validate_audio_input(audio, config=config)
        except VoiceValidationError:
            continue

        raise AssertionError("expected VoiceValidationError")


def test_stt_transcript_enters_existing_message_pipeline_and_tts_returns_audio():
    message_processor = FakeMessageProcessor(response_text="Mate rezervaciu?")
    stt_provider = FakeSTTProvider(text="Chcem rezervaciu dnes vecer")
    tts_provider = FakeTTSProvider()
    storage = FakeAudioStorage()
    service = build_service(
        build_tenant_context(),
        stt_provider=stt_provider,
        tts_provider=tts_provider,
        message_processor=message_processor,
        audio_storage=storage,
    )

    response = service.process(build_request())
    text_request = message_processor.requests[0]

    assert response.transcript == "Chcem rezervaciu dnes vecer"
    assert response.response_text == "Mate rezervaciu?"
    assert response.audio_url == "/voice/audio/conversation-1.mp3"
    assert text_request.channel == "voice"
    assert text_request.content == "Chcem rezervaciu dnes vecer"
    assert text_request.metadata["input_mode"] == "voice"
    assert text_request.metadata["original_channel"] == "browser"
    assert text_request.metadata["audio_content_type"] == "audio/webm"
    assert tts_provider.calls[0][0] == "Mate rezervaciu?"
    assert storage.saved[0][1] == "conversation-1"


def test_tts_failure_fallback_returns_text_response():
    service = build_service(
        build_tenant_context(fallback_tts=True),
        tts_provider=FailingTTSProvider(),
    )

    response = service.process(build_request())

    assert response.response_text == "Agent text response"
    assert response.audio_url is None
    assert response.audio is None
    assert response.metadata["warnings"] == ["TTS provider request failed"]


def test_tts_failure_without_fallback_raises_provider_error():
    service = build_service(
        build_tenant_context(fallback_tts=False),
        tts_provider=FailingTTSProvider(),
    )

    try:
        service.process(build_request())
    except VoiceTTSProviderError:
        return

    raise AssertionError("expected VoiceTTSProviderError")


def test_provider_selection_uses_tenant_voice_config():
    stt_provider = FakeSTTProvider()
    tts_provider = FakeTTSProvider()
    service = build_service(
        build_tenant_context(),
        stt_provider=stt_provider,
        tts_provider=tts_provider,
    )

    service.process(build_request())

    assert stt_provider.calls[0][1].model == "fake-stt-model"
    assert stt_provider.calls[0][1].language == "sk"
    assert tts_provider.calls[0][1].model == "fake-tts-model"
    assert tts_provider.calls[0][1].voice_id == "voice-1"
