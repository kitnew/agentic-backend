from collections.abc import Callable

from app.application.messages.process_incoming_message import ProcessIncomingMessage
from app.core.timing import (
    finish_timing_trace,
    new_timing_trace,
    record_component_timing,
    start_timer,
)
from app.domain.messages.enums import MessageStatus
from app.schemas.messages import CreateMessageRequest, ProcessMessageResponse
from app.tenants.loader import TenantConfigLoader
from app.voice.audio.storage import LocalVoiceAudioStorage
from app.voice.audio.validation import validate_audio_input
from app.voice.errors import (
    EmptyTranscriptError,
    VoiceAgentProcessingError,
    VoiceDisabledError,
    VoiceProviderNotFoundError,
    VoiceServiceError,
    VoiceSTTProviderError,
    VoiceTTSProviderError,
)
from app.voice.schemas import (
    AudioInput,
    FinalizedTranscriptRequest,
    SynthesizedAudioResult,
    TranscriptResult,
    VoiceMessageRequest,
    VoiceMessageResponse,
)
from app.voice.stt.base import STTProvider
from app.voice.stt.elevenlabs import ElevenLabsSTTProvider
from app.voice.tts.base import TTSProvider
from app.voice.tts.elevenlabs import ElevenLabsTTSProvider


class VoiceMessageService:
    def __init__(
        self,
        *,
        tenant_config_loader: TenantConfigLoader,
        message_processor: ProcessIncomingMessage | None = None,
        message_processor_factory: Callable[[], ProcessIncomingMessage] | None = None,
        stt_providers: dict[str, STTProvider] | None = None,
        tts_providers: dict[str, TTSProvider] | None = None,
        audio_storage: LocalVoiceAudioStorage | None = None,
    ):
        self.tenant_config_loader = tenant_config_loader
        self.message_processor = message_processor
        self.message_processor_factory = message_processor_factory
        self.stt_providers = stt_providers or {
            ElevenLabsSTTProvider.provider_name: ElevenLabsSTTProvider()
        }
        self.tts_providers = tts_providers or {
            ElevenLabsTTSProvider.provider_name: ElevenLabsTTSProvider()
        }
        self.audio_storage = audio_storage or LocalVoiceAudioStorage()

    def process(self, request: VoiceMessageRequest) -> VoiceMessageResponse:
        total_timer = start_timer()
        timings = new_timing_trace()
        component_timer = start_timer()
        tenant_context = self.tenant_config_loader.load(request.tenant_id)
        record_component_timing(timings, "tenant_config_load", component_timer)
        voice_config = tenant_context.voice

        if not voice_config.enabled:
            raise VoiceDisabledError("Voice mode is disabled for this tenant")

        component_timer = start_timer()
        audio = validate_audio_input(request.audio, config=voice_config)
        record_component_timing(
            timings,
            "audio_validation",
            component_timer,
            content_type=audio.content_type,
            size_bytes=audio.size_bytes,
        )
        stt_provider = self._get_stt_provider(voice_config.stt.provider)
        component_timer = start_timer()
        transcript_result = stt_provider.transcribe(audio, config=voice_config.stt)
        record_component_timing(
            timings,
            "stt",
            component_timer,
            provider=transcript_result.provider,
            model=voice_config.stt.model,
            language=transcript_result.language or voice_config.stt.language,
        )
        transcript = transcript_result.text.strip()

        if not transcript:
            raise EmptyTranscriptError("STT produced an empty transcript")

        warnings: list[str] = []
        if transcript_result.language is None or transcript_result.audio_duration_ms is None:
            if not voice_config.fallback.continue_if_stt_metadata_missing:
                raise VoiceSTTProviderError("STT metadata is missing")
            warnings.append("STT metadata missing; continuing with transcript only")

        return self._complete_transcript(
            request=request, transcript_result=transcript_result, voice_config=voice_config,
            timings=timings, total_timer=total_timer, warnings=warnings, audio=audio,
        )

    def process_transcript(
        self, request: FinalizedTranscriptRequest, *, text_callback=None, synthesize: bool = True
    ) -> VoiceMessageResponse:
        total_timer = start_timer()
        timings = new_timing_trace()
        voice_config = self.tenant_config_loader.load(request.tenant_id).voice
        if not voice_config.enabled:
            raise VoiceDisabledError("Voice mode is disabled for this tenant")
        transcript = request.transcript.strip()
        if not transcript:
            raise EmptyTranscriptError("STT produced an empty transcript")
        return self._complete_transcript(
            request=request,
            transcript_result=TranscriptResult(
                provider=request.provider, text=transcript, language=request.language,
                metadata={"model": request.model},
            ),
            voice_config=voice_config, timings=timings, total_timer=total_timer, warnings=[],
            text_callback=text_callback, synthesize=synthesize,
        )

    def _complete_transcript(
        self, *, request, transcript_result: TranscriptResult, voice_config,
        timings: dict, total_timer, warnings: list[str], audio: AudioInput | None = None,
        text_callback=None, synthesize: bool = True,
    ) -> VoiceMessageResponse:
        transcript = transcript_result.text.strip()

        component_timer = start_timer()
        message_response = self._process_transcript(
            request=request,
            audio=audio,
            transcript=transcript,
            transcript_provider=transcript_result.provider,
            text_callback=text_callback,
        )
        record_component_timing(
            timings,
            "agent_pipeline",
            component_timer,
            status=message_response.status,
        )
        response_text = (message_response.response_text or "").strip()
        if not response_text:
            raise VoiceAgentProcessingError("Agent produced an empty response")

        if (
            message_response.status == MessageStatus.FAILED
            and message_response.agent_trace
            and "error" in message_response.agent_trace
        ):
            raise VoiceAgentProcessingError("Agent failed to process the transcript")

        audio_result = None
        if synthesize:
            component_timer = start_timer()
            audio_result = self._try_synthesize_response(
                response_text=response_text,
                conversation_id=message_response.conversation_id,
                tenant_id=request.tenant_id,
                voice_config=voice_config,
                warnings=warnings,
            )
            record_component_timing(
                timings,
                "tts",
                component_timer,
                provider=voice_config.tts.provider,
                model=voice_config.tts.model,
                output_format=voice_config.tts.output_format,
                fallback_used=audio_result is None,
            )
        finished_timings = finish_timing_trace(timings, total_timer)
        agent_trace = {
            "input_mode": "voice",
            "voice_pipeline_timings": finished_timings,
            "text_agent_trace": message_response.agent_trace,
        }

        return VoiceMessageResponse(
            conversation_id=message_response.conversation_id,
            transcript=transcript,
            response_text=response_text,
            audio_url=audio_result.audio_url if audio_result else None,
            audio_base64=audio_result.audio_base64 if audio_result else None,
            transcript_result=transcript_result,
            audio=audio_result,
            agent_trace=agent_trace,
            metadata={
                "stt_provider": transcript_result.provider,
                "tts_provider": voice_config.tts.provider,
                "language": transcript_result.language or voice_config.stt.language,
                "audio_duration_ms": transcript_result.audio_duration_ms,
                "content_type": audio.content_type if audio else None,
                "input_mode": "voice",
                "original_channel": request.channel,
                "user_message_id": message_response.user_message.id,
                "assistant_message_id": (
                    message_response.assistant_message.id
                    if message_response.assistant_message
                    else None
                ),
                "warnings": warnings,
                "timings": finished_timings,
                "turn_kind": (
                    "tool_call" if message_response.requested_capabilities else "direct_response"
                ),
                "tool_execution_ms": sum(
                    tool.latency_ms or 0 for tool in message_response.tool_calls
                ) if message_response.tool_calls else None,
            },
        )

    def _process_transcript(
        self,
        *,
        request: VoiceMessageRequest,
        audio: AudioInput | None,
        transcript: str,
        transcript_provider: str,
        text_callback=None,
    ) -> ProcessMessageResponse:
        metadata = {
            **request.metadata,
            "input_mode": "voice",
            "stt_provider": transcript_provider,
            "original_channel": request.channel,
            "audio_content_type": audio.content_type if audio else None,
            "audio_filename": audio.filename if audio else None,
            "audio_size_bytes": audio.size_bytes if audio else None,
        }
        text_request = CreateMessageRequest(
            tenant_id=request.tenant_id,
            channel="voice",
            external_user_id=request.external_user_id,
            conversation_id=request.conversation_id,
            content=transcript,
            metadata=metadata,
        )
        if text_callback is None:
            return self._get_message_processor().execute(text_request)
        return self._get_message_processor().execute(text_request, text_callback=text_callback)

    def _try_synthesize_response(
        self,
        *,
        response_text: str,
        conversation_id: str,
        tenant_id: str,
        voice_config,
        warnings: list[str],
    ) -> SynthesizedAudioResult | None:
        tts_provider = self._get_tts_provider(voice_config.tts.provider)

        try:
            audio_result = tts_provider.synthesize(response_text, config=voice_config.tts)
            return self.audio_storage.save(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                audio=audio_result,
            )
        except VoiceServiceError as exc:
            if voice_config.fallback.send_text_if_tts_fails:
                warnings.append(exc.public_message)
                return None
            raise
        except Exception as exc:
            if voice_config.fallback.send_text_if_tts_fails:
                warnings.append("TTS failed; returning text response only")
                return None
            raise VoiceTTSProviderError("TTS failed") from exc

    def _get_stt_provider(self, provider_name: str) -> STTProvider:
        provider = self.stt_providers.get(provider_name)
        if not provider:
            raise VoiceProviderNotFoundError(f"STT provider not found: {provider_name}")
        return provider

    def _get_tts_provider(self, provider_name: str) -> TTSProvider:
        provider = self.tts_providers.get(provider_name)
        if not provider:
            raise VoiceProviderNotFoundError(f"TTS provider not found: {provider_name}")
        return provider

    def _get_message_processor(self) -> ProcessIncomingMessage:
        if self.message_processor is not None:
            return self.message_processor
        if self.message_processor_factory is not None:
            return self.message_processor_factory()
        raise VoiceAgentProcessingError("Message processor is not configured")
