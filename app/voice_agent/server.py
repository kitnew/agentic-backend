import json

from livekit.agents import AgentServer, AutoSubscribe, JobContext, JobProcess, cli
from livekit.plugins import silero

from app.infrastructure.database import SessionLocal
from app.infrastructure.repositories.conversation_repository import ConversationRepository
from app.tenants.loader import TenantConfigLoader
from app.voice_agent.graph_adapter import GraphStreamAdapter
from app.voice_agent.models import LiveKitJobMetadata
from app.voice_agent.session_factory import HospitalityAgent, build_session
from app.voice_agent.settings import LiveKitSettings
from app.voice_agent.telemetry import VoiceTelemetry


settings = LiveKitSettings.from_env()


def prewarm(proc: JobProcess) -> None:
    settings.validate_worker()
    proc.userdata["vad"] = silero.VAD.load(
        min_speech_duration=settings.min_speech_duration,
        min_silence_duration=settings.min_silence_duration,
        prefix_padding_duration=settings.prefix_padding_duration,
        activation_threshold=settings.vad_activation_threshold,
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
    expected_room = f"voice-{metadata.call_session_id}"
    if ctx.room.name != expected_room:
        raise ValueError("LiveKit room does not match job metadata")

    tenant = TenantConfigLoader().load(metadata.tenant_id)
    if not tenant.voice.enabled:
        raise ValueError("Voice mode is disabled for tenant")
    with SessionLocal() as db:
        conversation = ConversationRepository(db).get_by_id(str(metadata.conversation_id))
        if conversation is None or conversation.tenant_id != metadata.tenant_id:
            raise ValueError("Conversation does not belong to tenant")

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
    )
    telemetry.emit("room_connected")
    telemetry.emit("participant_connected")
    adapter = GraphStreamAdapter(metadata, telemetry, stt_model=settings.realtime_stt_model)
    session = build_session(settings, tenant, ctx.proc.userdata["vad"])
    telemetry.bind_session(session, on_user_speech_started=session.stt.mark_speech_started)

    async def cleanup(reason: str = "") -> None:
        await adapter.aclose()
        await session.aclose()
        await telemetry.aclose()

    ctx.add_shutdown_callback(cleanup)
    await session.start(agent=HospitalityAgent(adapter, telemetry), room=ctx.room)
    if tenant.agent.greeting_phrase:
        session.say(
            tenant.agent.greeting_phrase,
            allow_interruptions=True,
            add_to_chat_ctx=False,
        )


if __name__ == "__main__":
    cli.run_app(server)
