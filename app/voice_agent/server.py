import asyncio
import json
import logging
import time

from livekit.agents import AgentServer, AutoSubscribe, JobContext, JobProcess, cli
from livekit.plugins import silero

from app.voice_agent.backend_client import BackendCoreClient
from app.voice_agent.models import LiveKitJobMetadata
from app.voice_agent.session_factory import HospitalityAgent, VoiceTurnState, build_session
from app.voice_agent.settings import LiveKitSettings
from app.voice_agent.telemetry import VoiceTelemetry
from app.voice.session_token import VoiceSessionClaims, VoiceSessionTokenCodec


logger = logging.getLogger(__name__)
settings = LiveKitSettings.from_env()


def prewarm(_proc: JobProcess) -> None:
    settings.validate_worker()


def build_vad(turn_config):
    vad = turn_config.vad
    return silero.VAD.load(
        min_speech_duration=vad.min_speech_ms / 1000,
        min_silence_duration=vad.min_silence_ms / 1000,
        prefix_padding_duration=vad.prefix_padding_ms / 1000,
        activation_threshold=vad.activation_threshold,
    )


server = AgentServer(
    ws_url=settings.internal_url,
    api_key=settings.api_key or None,
    api_secret=settings.api_secret or None,
    host=settings.host,
    port=settings.port,
    drain_timeout=120,
    setup_fnc=prewarm,
)


@server.rtc_session(agent_name=settings.agent_name)
async def voice_agent(ctx: JobContext) -> None:
    metadata = LiveKitJobMetadata.parse_job(ctx.job.metadata)
    if ctx.room.name != f"voice-{metadata.call_session_id}":
        raise ValueError("LiveKit room does not match job metadata")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()

    async def publish(payload: dict) -> None:
        await ctx.room.local_participant.publish_data(
            json.dumps(payload, separators=(",", ":")),
            reliable=True,
            topic="voice.telemetry",
        )

    telemetry = VoiceTelemetry(
        {
            "tenant_id": metadata.tenant_id,
            "call_session_id": str(metadata.call_session_id),
            "conversation_id": str(metadata.conversation_id),
            "room_name": ctx.room.name,
            "participant_identity": participant.identity,
        },
        publisher=publish,
        configuration=metadata.turn_config,
    )
    telemetry.emit("room_connected")
    telemetry.emit("participant_connected")
    now = int(time.time())
    backend_token = VoiceSessionTokenCodec(settings.session_token_secret).encode(
        VoiceSessionClaims(
            tenant_id=metadata.tenant_id,
            call_session_id=str(metadata.call_session_id),
            conversation_id=str(metadata.conversation_id),
            language=metadata.language,
            timezone=metadata.timezone,
            iat=now,
            exp=now + settings.backend_token_ttl_seconds,
            mode="call",
        )
    )
    backend = BackendCoreClient(settings.backend_url, backend_token)
    state = VoiceTurnState()
    session = build_session(settings, metadata, build_vad(metadata.turn_config))
    agent = HospitalityAgent(metadata, backend, telemetry, state)
    persistence_tasks: set[asyncio.Task] = set()

    logger.info(
        "LiveKit session configuration preemptive_generation_enabled=%s "
        "preemptive_tts_enabled=false",
        metadata.turn_config.preemptive_generation.enabled,
    )

    @session.on("speech_created")
    def register_speech(event):
        if event.source == "generate_reply":
            state.register_speech(event.speech_handle)

    @session.on("conversation_item_added")
    def persist_conversation_item(event):
        item = event.item
        if getattr(item, "role", None) == "user":
            agent.accept_user_message(item)
            return
        if getattr(item, "role", None) != "assistant" or not state.current_turn_id:
            return
        task = asyncio.create_task(
            backend.persist_message(
                role="assistant",
                content=item.raw_text_content,
                turn_id=state.current_turn_id,
                item_id=item.id,
                interrupted=item.interrupted,
            )
        )
        persistence_tasks.add(task)
        task.add_done_callback(persistence_tasks.discard)
        task.add_done_callback(_log_persistence_failure)

    telemetry.bind_session(session, on_user_speech_started=session.stt.mark_speech_started)

    async def cleanup(_reason: str = "") -> None:
        state.close()
        pending = [*state.user_persistence.values(), *persistence_tasks]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await session.aclose()
        await backend.aclose()
        await telemetry.aclose()

    ctx.add_shutdown_callback(cleanup)
    await session.start(agent=agent, room=ctx.room)
    if metadata.greeting:
        session.say(metadata.greeting, allow_interruptions=True, add_to_chat_ctx=False)


def _log_persistence_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and (error := task.exception()):
        logger.error("Assistant message persistence failed: %s", error)


if __name__ == "__main__":
    cli.run_app(server)
