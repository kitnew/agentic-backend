import asyncio
import inspect
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from uuid import uuid4

from livekit.agents import Agent, AgentSession, RunContext, function_tool, llm, stt
from livekit.plugins import elevenlabs, openai

from app.voice_agent.backend_client import BackendCoreClient


logger = logging.getLogger(__name__)


class StableElevenLabsSTT(elevenlabs.STT):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._accept_interim = True

    def mark_speech_started(self) -> None:
        self._accept_interim = True

    def stream(self, **kwargs):
        return _PostFinalStream(super().stream(**kwargs), self)


class _PostFinalStream:
    def __init__(self, stream, provider):
        self._stream = stream
        self._provider = provider

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            event = await anext(self._stream)
            if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
                self._provider._accept_interim = False
                return event
            if event.type in {stt.SpeechEventType.START_OF_SPEECH, stt.SpeechEventType.INTERIM_TRANSCRIPT} and not self._provider._accept_interim:
                continue
            return event

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        await self._stream.aclose()


def resolve_voice_id(tenant) -> str:
    if tenant.voice.tts.voice_id:
        return tenant.voice.tts.voice_id
    if voice_id := os.getenv("ELEVENLABS_VOICE_ID", "").strip():
        return voice_id
    if voice_id := os.getenv("EVELENLABS_VOICE_ID", "").strip():
        logger.warning("EVELENLABS_VOICE_ID is deprecated; use ELEVENLABS_VOICE_ID")
        return voice_id
    raise ValueError("ElevenLabs voice ID is not configured")


def build_session(settings, metadata, vad) -> AgentSession:
    turn = metadata.turn_config
    segmentation = turn.stt_segmentation
    server_vad = None
    if segmentation.enabled:
        server_vad = {
            "vad_silence_threshold_secs": _seconds(segmentation.silence_ms),
            "vad_threshold": segmentation.threshold,
            "min_speech_duration_ms": segmentation.min_speech_ms,
            "min_silence_duration_ms": segmentation.min_silence_ms,
        }
    return AgentSession(
        stt=StableElevenLabsSTT(
            api_key=settings.elevenlabs_api_key,
            model_id=settings.realtime_stt_model,
            language_code=metadata.stt_language,
            include_timestamps=True,
            server_vad=server_vad,
            enable_logging=False,
        ),
        llm=openai.LLM.with_azure(
            azure_endpoint=settings.azure_openai_endpoint,
            azure_deployment=settings.azure_openai_deployment,
            api_version=settings.azure_openai_api_version,
            api_key=settings.azure_openai_api_key,
            temperature=0,
        ),
        tts=elevenlabs.TTS(
            api_key=settings.elevenlabs_api_key,
            voice_id=metadata.tts_voice_id,
            model=metadata.tts_model,
            language=metadata.tts_language,
            auto_mode=True,
            enable_logging=False,
        ),
        vad=vad,
        max_tool_steps=3,
        turn_handling={
            "turn_detection": "vad",
            "endpointing": {
                "mode": "fixed",
                "min_delay": _seconds(turn.endpointing.min_delay_ms),
                "max_delay": _seconds(turn.endpointing.max_delay_ms),
            },
            "interruption": {
                "enabled": turn.interruption.enabled,
                "mode": "vad",
                "discard_audio_if_uninterruptible": True,
                "min_duration": _seconds(turn.interruption.min_duration_ms),
                "min_words": turn.interruption.min_words,
                "false_interruption_timeout": _seconds(
                    turn.interruption.false_interruption_timeout_ms
                ),
                "resume_false_interruption": turn.interruption.resume_after_false_interruption,
            },
            "preemptive_generation": {"enabled": False, "preemptive_tts": False},
        },
    )


def build_chat_context(metadata) -> llm.ChatContext:
    context = llm.ChatContext.empty()
    for message in metadata.chat_history:
        context.add_message(role=message.role, content=message.content)
    return context


@dataclass
class VoiceTurnState:
    current_turn_id: str | None = None
    user_persistence: dict[str, asyncio.Task] = field(default_factory=dict)


def build_function_tools(metadata, backend: BackendCoreClient, state: VoiceTurnState, telemetry):
    async def execute(context: RunContext, capability: str, arguments: dict):
        turn_id = state.current_turn_id
        if turn_id is None:
            return {"status": "failed", "error": "voice turn is not initialized"}
        if task := state.user_persistence.get(turn_id):
            await task
        telemetry.set_turn_kind("tool_call")
        telemetry.emit("tool_call_started", tool_call_id=context.function_call.call_id, capability=capability)
        try:
            result = await backend.execute_tool(
                capability=capability,
                arguments=arguments,
                turn_id=turn_id,
                tool_call_id=context.function_call.call_id,
            )
        except Exception as exc:
            logger.exception("Backend Core tool call failed")
            result = {"status": "failed", "error": str(exc)}
        telemetry.emit("tool_call_completed", tool_call_id=context.function_call.call_id, capability=capability, status=result.get("status"))
        return result

    @function_tool(description="Check room availability for every night of a requested stay.")
    async def check_room_availability(
        context: RunContext,
        check_in: date,
        check_out: date,
        room_type: str,
        room_count: int,
    ) -> dict:
        return await execute(
            context,
            "reservation.check_availability",
            {"check_in": check_in.isoformat(), "check_out": check_out.isoformat(), "room_type": room_type, "room_count": room_count},
        )

    @function_tool(description="Submit a reservation request for staff confirmation after collecting all required fields.")
    async def create_reservation(
        context: RunContext,
        guest_name: str,
        date: str,
        time: str,
        party_size: int,
        phone: str,
        notes: str | None = None,
    ) -> dict:
        frame = {"guest_name": guest_name, "date": date, "time": time, "party_size": party_size, "phone": phone}
        if notes:
            frame["notes"] = notes
        return await execute(context, "reservation.create_request", {"reservation_frame": frame})

    tools = {
        "reservation.check_availability": check_room_availability,
        "reservation.create_request": create_reservation,
    }
    return [tools[name] for name in metadata.enabled_capabilities if name in tools]


class HospitalityAgent(Agent):
    def __init__(self, metadata, backend: BackendCoreClient, telemetry, state: VoiceTurnState):
        super().__init__(
            instructions=metadata.instructions,
            chat_ctx=build_chat_context(metadata),
            tools=build_function_tools(metadata, backend, state, telemetry),
        )
        self.backend = backend
        self.telemetry = telemetry
        self.state = state

    async def on_user_turn_completed(self, _turn_ctx, new_message) -> None:
        self.accept_user_message(new_message)

    def accept_user_message(self, new_message) -> None:
        if new_message.id in self.state.user_persistence:
            return
        self.state.current_turn_id = new_message.id
        self.telemetry.begin_turn(new_message.id, str(uuid4()))
        task = asyncio.create_task(
            self.backend.persist_message(
                role="user",
                content=new_message.raw_text_content,
                turn_id=new_message.id,
                item_id=new_message.id,
            )
        )
        self.state.user_persistence[new_message.id] = task
        task.add_done_callback(_log_persistence_failure)

    async def llm_node(self, chat_ctx, tools, model_settings):
        for item in reversed(chat_ctx.items):
            if getattr(item, "role", None) == "user":
                self.accept_user_message(item)
                break
        self.telemetry.emit("llm_request_started")
        stream = Agent.default.llm_node(self, chat_ctx, tools, model_settings)
        if inspect.isawaitable(stream):
            stream = await stream
        first = True
        async for chunk in stream:
            if first:
                first = False
                self.telemetry.emit("llm_first_chunk")
            yield chunk
        self.telemetry.emit("llm_completed")

    async def tts_node(self, text, model_settings):
        self.telemetry.emit("tts_request_started")
        stream = Agent.default.tts_node(self, text, model_settings)
        if inspect.isawaitable(stream):
            stream = await stream
        if stream is None:
            return
        first = True
        async for frame in stream:
            if first:
                first = False
                self.telemetry.emit("tts_first_audio")
            yield frame


def _seconds(milliseconds: int | None) -> float | None:
    return None if milliseconds is None else milliseconds / 1000


def _log_persistence_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and (error := task.exception()):
        logger.error("Voice message persistence failed: %s", error)
