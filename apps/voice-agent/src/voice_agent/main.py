import asyncio
import logging

from contracts import LiveKitJobMetadata, VoiceAgentRuntimeContext
from livekit import agents, rtc
from pydantic import ValidationError

from voice_agent.backend import BackendClient, CallFinalizer
from voice_agent.providers import create_agent_session
from voice_agent.settings import VoiceAgentSettings

logger = logging.getLogger(__name__)


def log_user_transcript(event: object) -> None:
    logger.info(
        "STT user input received",
        extra={
            "is_final": getattr(event, "is_final", None),
            "language": str(getattr(event, "language", "")),
            "transcript_length": len(getattr(event, "transcript", "") or ""),
        },
    )


def parse_metadata(raw_metadata: str) -> LiveKitJobMetadata:
    if not raw_metadata:
        raise ValueError("missing job metadata")
    return LiveKitJobMetadata.model_validate_json(raw_metadata)


def assemble_instructions(context: VoiceAgentRuntimeContext) -> str:
    return "\n\n".join(
        part
        for part in (
            context.prompt.system_instructions,
            context.prompt.tenant_instructions,
            context.prompt.knowledge_text,
            f"Locale: {context.locale}",
            f"Timezone: {context.timezone}",
            f"Conversation scope: {context.conversation_scope}",
        )
        if part
    )


def close_failure_reason(reason: agents.CloseReason) -> str | None:
    if reason in {
        agents.CloseReason.PARTICIPANT_DISCONNECTED,
        agents.CloseReason.USER_INITIATED,
        agents.CloseReason.TASK_COMPLETED,
    }:
        return None
    if reason is agents.CloseReason.JOB_SHUTDOWN:
        return "job_shutdown"
    return "provider_session_error"


async def on_request(request: agents.JobRequest) -> None:
    try:
        parse_metadata(request.job.metadata)
    except (ValueError, ValidationError):
        await request.reject(terminate=True)
        return
    await request.accept()


async def run_job(
    ctx: agents.JobContext,
    settings: VoiceAgentSettings,
) -> None:
    metadata = parse_metadata(ctx.job.metadata)
    backend = BackendClient(settings)
    finalizer = CallFinalizer(backend, metadata.call_session_id)
    session: agents.AgentSession | None = None
    try:
        context = await backend.runtime_context(metadata.call_session_id)
        session = create_agent_session(settings, context.locale)
        closed = asyncio.get_running_loop().create_future()

        def on_close(event: agents.CloseEvent) -> None:
            if not closed.done():
                closed.set_result(event)

        session.on("close", on_close)
        session.on("user_input_transcribed", log_user_transcript)
        await session.start(
            room=ctx.room,
            agent=agents.Agent(
                instructions=assemble_instructions(context),
                tools=[],
            ),
        )
        try:
            await asyncio.wait_for(
                ctx.wait_for_participant(
                    kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD
                ),
                timeout=settings.participant_wait_timeout_seconds,
            )
        except TimeoutError:
            await finalizer.fail("participant_timeout")
            await session.aclose()
            return

        await backend.activate(metadata.call_session_id)
        if not closed.done():
            try:
                await session.say(context.greeting)
            except Exception:
                if not closed.done():
                    raise
        close_event = await closed
        failure_reason = close_failure_reason(close_event.reason)
        if failure_reason is None:
            await finalizer.complete()
        else:
            await finalizer.fail(failure_reason)
    except asyncio.CancelledError:
        await finalizer.fail("job_shutdown")
        if session is not None:
            await session.aclose()
        raise
    except Exception:
        logger.exception("Voice Agent job failed", extra={"call_session_id": str(metadata.call_session_id)})
        await finalizer.fail("provider_session_error")
        if session is not None:
            await session.aclose()
    finally:
        await backend.aclose()


async def entrypoint(ctx: agents.JobContext) -> None:
    await run_job(ctx, VoiceAgentSettings())  # type: ignore[call-arg]


def build_server(settings: VoiceAgentSettings) -> agents.AgentServer:
    server = agents.AgentServer(
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key.get_secret_value(),
        api_secret=settings.livekit_api_secret.get_secret_value(),
    )

    server.rtc_session(
        agent_name=settings.livekit_agent_name,
        on_request=on_request,
    )(entrypoint)

    return server


def main() -> None:
    agents.cli.run_app(build_server(VoiceAgentSettings()))  # type: ignore[call-arg]


if __name__ == "__main__":
    main()
