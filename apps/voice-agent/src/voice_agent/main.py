import asyncio
import logging
from typing import Any, cast
from uuid import UUID

import httpx
from contracts import (
    CapabilityInvocationRequest,
    CapabilityInvocationStatus,
    LiveKitJobMetadata,
    RuntimeCapabilityDefinition,
    VoiceAgentRuntimeContext,
)
from livekit import agents, rtc
from livekit.agents import llm
from pydantic import ValidationError

from voice_agent.backend import BackendClient, CallFinalizer
from voice_agent.persistence import ConversationPersistence
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


def log_session_metrics(event: object) -> None:
    metrics = getattr(event, "metrics", None)
    if metrics is None or getattr(metrics, "type", None) != "eou_metrics":
        return
    logger.info(
        "Voice EOU metrics",
        extra={
            "end_of_utterance_delay": metrics.end_of_utterance_delay,
            "transcription_delay": metrics.transcription_delay,
            "on_user_turn_completed_delay": metrics.on_user_turn_completed_delay,
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
            "Use a capability tool when its inputs are known. Do not promise success before its result. reservation_submit_request submits a request; it never confirms a reservation.",
        )
        if part
    )


def capability_tool(
    definition: RuntimeCapabilityDefinition,
    backend: BackendClient,
    call_id: UUID,
) -> llm.RawFunctionTool:
    async def invoke(
        context: agents.RunContext[Any],
        raw_arguments: dict[str, object],
    ) -> dict[str, object]:
        announcement = context.session.say(
            definition.announcement,
            allow_interruptions=False,
            add_to_chat_ctx=False,
        )
        await announcement
        try:
            invocation = await backend.invoke_capability(
                call_id,
                CapabilityInvocationRequest(
                    tool_call_id=context.function_call.call_id,
                    capability=definition.tool_name,
                    agent_input=raw_arguments,
                ),
            )
            invocation = await backend.wait_for_capability(call_id, invocation)
        except TimeoutError:
            return {
                "status": "request_submission_pending",
                "error_code": "execution_timeout",
                "message": "The request is still being processed; I could not confirm submission yet",
            }
        except httpx.HTTPError:
            return {
                "status": "request_submission_failed",
                "error_code": "execution_timeout",
                "message": "The reservation request could not be submitted yet",
            }
        if invocation.status is CapabilityInvocationStatus.SUCCEEDED:
            assert invocation.semantic_result is not None
            return invocation.semantic_result.model_dump(mode="json")
        return {
            "status": "request_submission_failed",
            "error_code": invocation.error_code or "execution_failed",
            "message": invocation.error_message
            or "The reservation request could not be submitted",
        }

    return cast(
        llm.RawFunctionTool,
        agents.function_tool(
            raw_schema={
                "name": definition.tool_name,
                "description": definition.description,
                "parameters": definition.input_schema,
            }
        )(invoke),
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
    except ValueError, ValidationError:
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
    persistence: ConversationPersistence | None = None
    failure_reason: str | None = None
    cancelled = False
    try:
        context = await backend.runtime_context(metadata.call_session_id)
        session = create_agent_session(settings, context.locale)
        persistence = ConversationPersistence(backend, metadata.call_session_id)
        closed = asyncio.get_running_loop().create_future()

        def on_close(event: agents.CloseEvent) -> None:
            if not closed.done():
                closed.set_result(event)

        session.on("close", on_close)
        session.on("conversation_item_added", persistence.on_conversation_item_added)
        session.on("user_input_transcribed", log_user_transcript)
        session.on("metrics_collected", log_session_metrics)
        await session.start(
            room=ctx.room,
            agent=agents.Agent(
                instructions=assemble_instructions(context),
                tools=[
                    capability_tool(tool, backend, metadata.call_session_id)
                    for tool in context.capabilities
                ],
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
            failure_reason = "participant_timeout"
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
    except asyncio.CancelledError:
        failure_reason = "job_shutdown"
        cancelled = True
        if session is not None:
            await session.aclose()
    except Exception:
        logger.exception(
            "Voice Agent job failed",
            extra={"call_session_id": str(metadata.call_session_id)},
        )
        failure_reason = "provider_session_error"
        if session is not None:
            await session.aclose()
    finally:
        if session is not None and persistence is not None:
            off = getattr(session, "off", None)
            if off is not None:
                off("conversation_item_added", persistence.on_conversation_item_added)
        conversation_complete = False
        if persistence is not None:
            try:
                conversation_complete = await persistence.finish()
            except Exception:
                logger.exception("conversation persistence drain failed")
        conversation_status = "complete" if conversation_complete else "incomplete"
        try:
            if failure_reason is None:
                await finalizer.complete(conversation_status)
            else:
                await finalizer.fail(failure_reason, conversation_status)
        finally:
            await backend.aclose()
    if cancelled:
        raise asyncio.CancelledError


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
