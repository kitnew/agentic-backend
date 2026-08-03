import asyncio
import json
import logging
import time
from uuid import uuid4

from livekit import api, rtc
from livekit.agents import AgentServer, AutoSubscribe, JobContext, JobProcess, cli
from livekit.plugins import silero

from app.contracts.livekit import (
    LiveKitBackendClaims,
    LiveKitBootstrapClaims,
    LiveKitBackendTokenCodec,
    LiveKitJobMetadata,
    InboundSipBootstrapRequest,
)
from app.voice_agent.backend_client import BackendCoreClient
from app.voice_agent.session_factory import HospitalityAgent, VoiceTurnState, build_session
from app.voice_agent.settings import LiveKitSettings
from app.voice_agent.telemetry import VoiceTelemetry
from app.tenants.schemas import normalize_phone_number


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


def build_inbound_bootstrap_request(
    room_name: str, participant
) -> InboundSipBootstrapRequest:
    attributes = participant.attributes
    return InboundSipBootstrapRequest(
        room_name=room_name,
        participant_identity=participant.identity,
        sip_call_id=attributes.get("sip.callID") or None,
        sip_call_id_full=attributes.get("sip.callIDFull") or None,
        sip_trunk_id=attributes.get("sip.trunkID") or None,
        sip_rule_id=attributes.get("sip.ruleID") or None,
        caller_number=(
            normalize_phone_number(attributes["sip.phoneNumber"])
            if attributes.get("sip.phoneNumber")
            else None
        ),
        called_number=normalize_phone_number(
            attributes.get("sip.trunkPhoneNumber") or ""
        ),
    )


def build_human_handoff_request(
    room_name: str, phone_number: str, trunk_id: str, participant_identity: str
) -> api.CreateSIPParticipantRequest:
    return api.CreateSIPParticipantRequest(
        sip_trunk_id=trunk_id,
        sip_call_to=phone_number,
        room_name=room_name,
        participant_identity=participant_identity,
        wait_until_answered=True,
    )


@server.rtc_session(agent_name=settings.agent_name)
async def voice_agent(ctx: JobContext) -> None:
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    is_sip = (
        getattr(participant, "kind", None)
        == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
    )
    metadata = None
    backend_token = None
    request = None
    if is_sip:
        attributes = participant.attributes
        logger.info(
            "event=sip_participant_discovered room_name=%s participant_identity=%s "
            "sip_call_id=%s trunk_id=%s rule_id=%s",
            ctx.room.name,
            participant.identity,
            attributes.get("sip.callIDFull") or attributes.get("sip.callID"),
            attributes.get("sip.trunkID"),
            attributes.get("sip.ruleID"),
        )
        try:
            request = build_inbound_bootstrap_request(ctx.room.name, participant)
        except ValueError:
            logger.exception(
                "event=inbound_bootstrap_rejected room_name=%s participant_identity=%s "
                "reason=invalid_sip_attributes",
                ctx.room.name,
                participant.identity,
            )
            return
        now = int(time.time())
        bootstrap_token = LiveKitBackendTokenCodec(
            settings.session_token_secret
        ).encode_bootstrap(
            LiveKitBootstrapClaims(
                iat=now,
                exp=now + min(settings.backend_token_ttl_seconds, 300),
            )
        )
        bootstrap = BackendCoreClient(settings.backend_url, bootstrap_token)
        try:
            logger.info(
                "event=inbound_bootstrap_requested room_name=%s participant_identity=%s "
                "sip_call_id=%s trunk_id=%s rule_id=%s",
                ctx.room.name,
                participant.identity,
                request.sip_call_id_full or request.sip_call_id,
                request.sip_trunk_id,
                request.sip_rule_id,
            )
            response = await bootstrap.bootstrap_inbound(request)
        except Exception:
            logger.exception(
                "event=inbound_bootstrap_failed room_name=%s participant_identity=%s "
                "sip_call_id=%s trunk_id=%s rule_id=%s",
                ctx.room.name,
                participant.identity,
                request.sip_call_id_full or request.sip_call_id,
                request.sip_trunk_id,
                request.sip_rule_id,
            )
            return
        finally:
            await bootstrap.aclose()
        metadata = response.job_metadata
        backend_token = response.backend_token
    else:
        metadata = LiveKitJobMetadata.parse_job(ctx.job.metadata)
    if metadata.origin == "browser" and ctx.room.name != f"voice-{metadata.call_session_id}":
        raise ValueError("LiveKit room does not match job metadata")

    async def publish(payload: dict) -> None:
        await ctx.room.local_participant.publish_data(
            json.dumps(payload, separators=(",", ":")),
            reliable=True,
            topic="voice.telemetry",
        )

    telemetry_context = {
            "tenant_id": metadata.tenant_id,
            "call_session_id": str(metadata.call_session_id),
            "conversation_id": str(metadata.conversation_id),
            "room_name": ctx.room.name,
            "participant_identity": participant.identity,
    }
    if is_sip:
        telemetry_context.update(
            {
                "sip_call_id": participant.attributes.get("sip.callIDFull")
                or participant.attributes.get("sip.callID"),
                "trunk_id": participant.attributes.get("sip.trunkID"),
                "rule_id": participant.attributes.get("sip.ruleID"),
            }
        )
    telemetry = VoiceTelemetry(
        telemetry_context,
        publisher=publish,
        configuration=metadata.turn_config,
    )
    telemetry.emit("room_connected")
    telemetry.emit("participant_connected")
    if is_sip:
        telemetry.emit("sip_participant_discovered")
    if backend_token is None:
        now = int(time.time())
        backend_token = LiveKitBackendTokenCodec(settings.session_token_secret).encode(
            LiveKitBackendClaims(
                tenant_id=metadata.tenant_id,
                call_session_id=str(metadata.call_session_id),
                conversation_id=str(metadata.conversation_id),
                language=metadata.language,
                timezone=metadata.timezone,
                iat=now,
                exp=now + settings.backend_token_ttl_seconds,
            )
        )
    backend = BackendCoreClient(settings.backend_url, backend_token)
    state = VoiceTurnState()
    session = build_session(settings, metadata, build_vad(metadata.turn_config))
    caller_number = (
        request.caller_number
        if request is not None
        else participant.attributes.get("sip.phoneNumber") or None
    )
    persistence_tasks: set[asyncio.Task] = set()
    finalization_started = False
    handoff_active = False
    handoff_identity = None
    handoff_ending = False

    async def end_handoff(reason: str) -> None:
        nonlocal handoff_ending
        if handoff_ending:
            return
        handoff_ending = True
        try:
            await ctx.delete_room()
        except Exception:
            logger.exception("Human handoff room deletion failed room_name=%s", ctx.room.name)
        ctx.shutdown(reason)

    def handle_handoff_disconnect(disconnected) -> None:
        if handoff_active and disconnected.identity in {participant.identity, handoff_identity}:
            asyncio.create_task(
                end_handoff("human handoff participant disconnected")
            )

    room_on = getattr(ctx.room, "on", None)
    if room_on:
        room_on("participant_disconnected")(handle_handoff_disconnect)

    async def handoff_to_human(context) -> str:
        nonlocal handoff_active, handoff_identity
        if handoff_active:
            return "Human handoff is already active."
        identity = f"human-handoff-{uuid4().hex}"
        client = api.LiveKitAPI(
            url=settings.api_url,
            api_key=settings.api_key,
            api_secret=settings.api_secret,
        )
        try:
            await client.sip.create_sip_participant(
                build_human_handoff_request(
                    ctx.room.name,
                    metadata.outbound_dids[0],
                    metadata.outbound_trunk_id,
                    identity,
                )
            )
        except Exception:
            logger.exception(
                "Human handoff outbound call failed room_name=%s participant_identity=%s",
                ctx.room.name,
                identity,
            )
            return "Human handoff could not be started."
        finally:
            await client.aclose()
        handoff_identity = identity
        handoff_active = True
        telemetry.emit("human_handoff_started", participant_identity=identity)
        context.session.shutdown(drain=True)
        return "Human handoff started."

    human_handoff = (
        handoff_to_human
        if is_sip and metadata.handoff
        else None
    )
    agent = HospitalityAgent(
        metadata,
        backend,
        telemetry,
        state,
        caller_number,
        human_handoff,
    )

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
        nonlocal finalization_started
        state.close()
        pending = [*state.user_persistence.values(), *persistence_tasks]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        finalized = False
        if not finalization_started:
            finalization_started = True
            try:
                await backend.finalize_call(
                    call_session_id=str(metadata.call_session_id),
                    outcome="failed" if "error" in _reason.casefold() else "completed",
                    reason=_reason or None,
                    error=_reason if "error" in _reason.casefold() else None,
                    livekit_job_id=str(getattr(ctx.job, "id", "")) or None,
                    caller_phone=caller_number,
                )
                finalized = True
            except Exception:
                logger.exception(
                    "Backend Core call finalization request failed tenant_id=%s "
                    "call_session_id=%s conversation_id=%s",
                    metadata.tenant_id,
                    metadata.call_session_id,
                    metadata.conversation_id,
                )
        if is_sip and finalized:
            telemetry.emit("sip_call_finalized")
        await session.aclose()
        await backend.aclose()
        await telemetry.aclose()

    ctx.add_shutdown_callback(cleanup)
    await session.start(agent=agent, room=ctx.room)
    telemetry.emit("agent_session_started")
    if metadata.greeting:
        session.say(metadata.greeting, allow_interruptions=True, add_to_chat_ctx=False)


def _log_persistence_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and (error := task.exception()):
        logger.error("Assistant message persistence failed: %s", error)


if __name__ == "__main__":
    cli.run_app(server)
