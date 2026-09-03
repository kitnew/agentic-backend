import asyncio
import hashlib
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from contracts import (
    CapabilityInvocationRequest,
    CapabilityInvocationStatus,
    HumanHandoffRequest,
    InboundSipClaimRequest,
    LiveKitJobMetadata,
    RuntimeCapabilityDefinition,
    VoiceAgentRuntimeContext,
)
from livekit import agents, rtc
from livekit.agents import llm
from livekit.agents.beta.tools import EndCallTool
from pydantic import ValidationError

from voice_agent.backend import BackendClient, CallFinalizer
from voice_agent.calculator import calculator_tool
from voice_agent.event_delivery import ConversationPersistence
from voice_agent.observability import (
    LatencyInstrumentedAgent,
    current_voice_telemetry,
    record_capability_execution,
    setup_voice_telemetry,
    shutdown_voice_telemetry,
)
from voice_agent.providers import create_agent_session, create_realtime_session
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


def log_runtime_binding(
    settings: VoiceAgentSettings, context: VoiceAgentRuntimeContext
) -> None:
    if context.voice_runtime is None:
        logger.info(
            "Realtime runtime binding resolved",
            extra={"call_session_id": str(context.call_session_id)},
        )
        return
    runtime = context.voice_runtime
    logger.info(
        "Voice runtime binding resolved",
        extra={
            "call_session_id": str(context.call_session_id),
            "voice_runtime_revision_id": str(context.voice_runtime_revision_id),
            "llm_provider": runtime.llm.provider,
            "llm_logical_model": runtime.llm.model,
            "stt_provider": runtime.stt.provider,
            "stt_model": runtime.stt.model,
            "tts_provider": runtime.tts.provider,
            "tts_model": runtime.tts.model,
            "tts_voice_id": runtime.tts.voice_id,
        },
    )


def parse_metadata(raw_metadata: str) -> LiveKitJobMetadata:
    if not raw_metadata:
        raise ValueError("missing job metadata")
    return LiveKitJobMetadata.model_validate_json(raw_metadata)


async def resolve_call_session_id(
    ctx: agents.JobContext,
    backend: BackendClient,
    timeout: float,
) -> UUID:
    if ctx.job.metadata.strip():
        return parse_metadata(ctx.job.metadata).call_session_id
    participant = await asyncio.wait_for(
        ctx.wait_for_participant(
            kind=[
                rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
                rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
            ]
        ),
        timeout=timeout,
    )
    if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        raise ValueError("job without call_session_id has no inbound SIP participant")
    attributes = participant.attributes
    required = {
        "sip.callID": "sip_call_id",
        "sip.phoneNumber": "caller_number",
        "sip.trunkPhoneNumber": "called_number",
        "sip.trunkID": "trunk_id",
        "sip.ruleID": "dispatch_rule_id",
    }
    missing = [key for key in required if not attributes.get(key)]
    if missing:
        raise ValueError(f"inbound SIP participant missing {', '.join(missing)}")
    logger.info(
        "Inbound SIP participant discovered",
        extra={
            "sip_call_id": attributes["sip.callID"],
            "room": ctx.room.name,
            "participant_identity": participant.identity,
        },
    )
    claim = await backend.claim_inbound_sip(
        InboundSipClaimRequest(
            sip_call_id=attributes["sip.callID"],
            sip_call_id_full=attributes.get("sip.callIDFull") or None,
            trunk_id=attributes["sip.trunkID"],
            dispatch_rule_id=attributes["sip.ruleID"],
            caller_number=attributes["sip.phoneNumber"],
            called_number=attributes["sip.trunkPhoneNumber"],
            room_name=ctx.room.name,
            participant_identity=participant.identity,
        )
    )
    logger.info(
        "Inbound SIP claim completed",
        extra={
            "call_session_id": str(claim.call_session_id),
            "sip_call_id": attributes["sip.callID"],
            "room": ctx.room.name,
            "call_session_created": claim.created,
        },
    )
    return claim.call_session_id


def assemble_instructions(context: VoiceAgentRuntimeContext) -> str:
    local_now = datetime.now(ZoneInfo(context.timezone))
    return "\n\n".join(
        part
        for part in (
            context.prompt.system_prompt,
            context.prompt.profile_prompt,
            context.prompt.tenant_prompt,
            f"Locale: {context.locale}",
            f"Timezone: {context.timezone}",
            f"Current local date: {local_now.date().isoformat()}",
            f"Current local time: {local_now.strftime('%H:%M:%S')}",
            f"Conversation scope: {context.conversation_scope}",
            "Use a capability tool when its inputs are known. Do not promise success before its result. Capability results are authoritative for the requested operation.",
            "Use the calculator whenever exact arithmetic is required. It performs one operation per call; decompose multi-step calculations into sequential calls and pass each result forward. It does not interpret business meaning. percentage(A, B) means B percent of A.",
            context.prompt.knowledge_context,
        )
        if part
    )


def build_agent_tools(
    context: VoiceAgentRuntimeContext,
    backend: BackendClient,
    call_id: UUID,
    on_handoff: Callable[[], None] | None = None,
    capability_recorder: Callable[..., None] | None = None,
) -> list[llm.Tool | llm.Toolset]:
    recorder = capability_recorder or record_capability_execution
    end_call_started: dict[int, float] = {}

    async def on_end_call_called(event: llm.Toolset.ToolCalledEvent) -> None:
        end_call_started[id(event.ctx)] = time.perf_counter()

    async def on_end_call_completed(event: llm.Toolset.ToolCompletedEvent) -> None:
        started = end_call_started.pop(id(event.ctx), None)
        if started is not None:
            recorder(
                name="call.end",
                version="1",
                status="failed" if isinstance(event.output, Exception) else "ok",
                duration_seconds=time.perf_counter() - started,
                error_type=(
                    "execution_error" if isinstance(event.output, Exception) else None
                ),
            )

    return [
        calculator_tool(recorder),
        EndCallTool(
            delete_room=True,
            ignore_on_enter=True,
            on_tool_called=on_end_call_called,
            on_tool_completed=on_end_call_completed,
        ),
        *(
            [handoff_tool(context, backend, call_id, on_handoff)]
            if context.handoff_destinations
            else []
        ),
        *[
            capability_tool(tool, backend, call_id, recorder)
            for tool in context.capabilities
        ],
    ]


def handoff_tool(
    runtime: VoiceAgentRuntimeContext,
    backend: BackendClient,
    call_id: UUID,
    on_handoff: Callable[[], None] | None = None,
) -> llm.RawFunctionTool:
    destinations = runtime.handoff_destinations
    description = "; ".join(
        f"{key}: {value.description}" for key, value in destinations.items()
    )

    async def invoke(
        context: agents.RunContext[Any],
        raw_arguments: dict[str, object],
    ) -> Any:
        request = HumanHandoffRequest.model_validate(
            {"tool_call_id": context.function_call.call_id, **raw_arguments}
        )
        try:
            result = await backend.transfer_to_human(call_id, request)
        except httpx.HTTPStatusError as error:
            code = "transfer_failed"
            try:
                candidate = error.response.json()["detail"]["code"]
                if candidate in {
                    "handoff_not_configured",
                    "unknown_destination",
                    "call_not_transferable",
                    "transfer_failed",
                    "outbound_unavailable",
                }:
                    code = candidate
            except KeyError, TypeError, ValueError:
                pass
            return {"status": "failed", "error_code": code}
        except httpx.HTTPError:
            return {"status": "failed", "error_code": "transfer_failed"}
        if on_handoff is not None:
            on_handoff()
        context.session.shutdown(drain=True)
        return result.model_dump(mode="json")

    return cast(
        llm.RawFunctionTool,
        agents.function_tool(
            raw_schema={
                "name": "transfer_to_human",
                "description": (
                    "Transfer the caller to one configured human destination. "
                    f"Available destinations: {description}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "destination": {
                            "type": "string",
                            "enum": list(destinations),
                            "description": "Semantic destination key",
                        },
                        "reason": {
                            "type": "string",
                            "maxLength": 500,
                            "description": "Optional short reason for the transfer",
                        },
                    },
                    "required": ["destination"],
                    "additionalProperties": False,
                },
            }
        )(invoke),
    )


def capability_tool(
    definition: RuntimeCapabilityDefinition,
    backend: BackendClient,
    call_id: UUID,
    capability_recorder: Callable[..., None] | None = None,
) -> llm.RawFunctionTool:
    recorder = capability_recorder or record_capability_execution
    pending_confirmation: dict[str, object] = {}

    async def invoke(
        context: agents.RunContext[Any],
        raw_arguments: dict[str, object],
    ) -> Any:
        announcement = context.session.say(
            definition.announcement,
            allow_interruptions=False,
            add_to_chat_ctx=False,
        )
        await announcement
        started = time.perf_counter()
        executed = False
        status = "failed"
        error_type: str | None = None
        result: Any
        try:
            request = CapabilityInvocationRequest(
                tool_call_id=context.function_call.call_id,
                capability=definition.tool_name,
                agent_input=raw_arguments,
            )
            pending_id = pending_confirmation.get("id")
            if not definition.requires_confirmation:
                executed = True
                invocation = await backend.invoke_capability(call_id, request)
            elif (
                pending_id is not None
                and pending_confirmation.get("agent_input") == raw_arguments
            ):
                executed = True
                invocation = await backend.confirm_capability(
                    call_id, UUID(str(pending_id)), context.function_call.call_id
                )
                pending_confirmation.clear()
            else:
                confirmation = await backend.prepare_confirmation(call_id, request)
                pending_confirmation.update(
                    {"id": confirmation.id, "agent_input": dict(raw_arguments)}
                )
                result = {
                    "status": confirmation.status,
                    "confirmation_id": str(confirmation.id),
                    "summary": confirmation.summary,
                    "message": "Please confirm these reservation details before submission.",
                }
            if executed:
                invocation = await backend.wait_for_capability(call_id, invocation)
                if invocation.status is CapabilityInvocationStatus.SUCCEEDED:
                    status = "ok"
                    result = (
                        invocation.semantic_result
                        if invocation.semantic_result is not None
                        else {"status": "submitted"}
                    )
                else:
                    result = {
                        "status": "request_submission_failed",
                        "error_code": invocation.error_code or "execution_failed",
                        "message": invocation.error_message
                        or "The reservation request could not be submitted",
                    }
        except TimeoutError:
            error_type = "execution_timeout"
            result = {
                "status": "request_submission_pending",
                "error_code": "execution_timeout",
                "message": "The request is still being processed; I could not confirm submission yet",
            }
        except httpx.HTTPError:
            error_type = "http_error"
            result = {
                "status": "request_submission_failed",
                "error_code": "execution_timeout",
                "message": "The reservation request could not be submitted yet",
            }
        except Exception:
            error_type = "execution_error"
            raise
        finally:
            if executed:
                recorder(
                    name=definition.semantic_key,
                    version=str(definition.semantic_version),
                    status=status,
                    duration_seconds=time.perf_counter() - started,
                    error_type=error_type,
                )
        return result

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


class SessionTerminalizer:
    def __init__(
        self,
        finalizer: CallFinalizer,
        persistence: ConversationPersistence,
    ) -> None:
        self._finalizer = finalizer
        self._persistence = persistence
        self._task: asyncio.Task[None] | None = None

    def start(self, failure_reason: str | None) -> asyncio.Task[None]:
        if self._task is None:
            self._task = asyncio.create_task(self._deliver(failure_reason))
        return self._task

    async def terminalize(self, failure_reason: str | None) -> None:
        task = self.start(failure_reason)
        await asyncio.shield(task)

    async def _deliver(self, failure_reason: str | None) -> None:
        conversation_complete = False
        try:
            conversation_complete = await self._persistence.finish()
        except Exception:
            logger.exception("conversation persistence drain failed")
        conversation_status = "complete" if conversation_complete else "incomplete"
        if failure_reason is None:
            await self._finalizer.complete(conversation_status)
        else:
            await self._finalizer.fail(failure_reason, conversation_status)


async def on_request(request: agents.JobRequest) -> None:
    if request.job.metadata.strip():
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
    backend = BackendClient(settings)
    call_id: UUID | None = None
    finalizer: CallFinalizer | None = None
    session: agents.AgentSession | None = None
    persistence: ConversationPersistence | None = None
    terminalizer: SessionTerminalizer | None = None
    failure_reason: str | None = None
    handed_off = False
    cancelled = False
    try:
        call_id = await resolve_call_session_id(
            ctx, backend, settings.participant_wait_timeout_seconds
        )
        finalizer = CallFinalizer(backend, call_id)
        context = await backend.runtime_context(call_id)
        logger.info(
            "Voice runtime context loaded",
            extra={"call_session_id": str(call_id), "room": context.room_name},
        )
        log_runtime_binding(settings, context)
        prompt_cache_key = (
            "voice-agent-prompt:"
            + hashlib.sha256(
                f"{context.prompt.system_prompt}\0{context.prompt.profile_prompt}".encode()
            ).hexdigest()
        )
        telemetry = current_voice_telemetry()
        secrets = {}
        if context.execution_snapshot_id is not None:
            slots = (
                ("model", "input_transcription")
                if context.architecture == "realtime"
                else ("stt", "llm", "tts")
            )
            secrets = {
                slot: await backend.runtime_secret(context.execution_snapshot_id, slot)
                for slot in slots
            }
        if context.architecture == "realtime":
            if context.snapshot_runtime is None:
                raise ValueError("realtime execution snapshot is missing runtime")
            session = create_realtime_session(settings, context.snapshot_runtime, secrets)
        else:
            if context.voice_runtime is None:
                raise ValueError("cascade execution snapshot is missing runtime")
            session = create_agent_session(
                settings,
                context.voice_runtime,
                prompt_cache_key,
                telemetry.metrics if telemetry is not None else None,
                secrets,
                context.snapshot_runtime,
            )
        persistence = ConversationPersistence(backend, call_id)
        terminalizer = SessionTerminalizer(finalizer, persistence)
        closed = asyncio.get_running_loop().create_future()

        def mark_handed_off() -> None:
            nonlocal handed_off
            handed_off = True

        async def on_shutdown(_: str) -> None:
            if not handed_off:
                await terminalizer.terminalize("job_shutdown")

        ctx.add_shutdown_callback(on_shutdown)

        def on_close(event: agents.CloseEvent) -> None:
            if not closed.done():
                closed.set_result(event)
            if handed_off:
                return
            task = terminalizer.start(close_failure_reason(event.reason))
            task.add_done_callback(log_terminalization_failure)

        session.on("close", on_close)
        session.on("conversation_item_added", persistence.on_conversation_item_added)
        if telemetry is not None:
            telemetry.metrics.attach_speculative_generation(session)
            session.on(
                "conversation_item_added",
                lambda event: telemetry.metrics.record_turn(
                    getattr(event, "item", None)
                ),
            )
        session.on("user_input_transcribed", log_user_transcript)
        await session.start(
            room=ctx.room,
            # Keep native spans local to the explicit OTLP pipeline. LiveKit Cloud
            # recording can create a second provider and retain conversation data.
            record={
                "audio": False,
                "traces": False,
                "logs": False,
                "transcript": False,
            },
            agent=LatencyInstrumentedAgent(
                metrics=telemetry.metrics if telemetry is not None else None,
                instructions=assemble_instructions(context),
                tools=build_agent_tools(
                    context,
                    backend,
                    call_id,
                    mark_handed_off,
                    telemetry.metrics.record_capability_execution
                    if telemetry is not None
                    else None,
                ),
            ),
        )
        if telemetry is not None:
            telemetry.metrics.attach_eot_decomposition(session)
            telemetry.set_session_correlation(call_id)
        observe = getattr(backend, "observe", None)
        if observe is not None:
            await observe(call_id, "session_started")
        try:
            await asyncio.wait_for(
                ctx.wait_for_participant(
                    kind=[
                        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
                        rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
                    ]
                ),
                timeout=settings.participant_wait_timeout_seconds,
            )
        except TimeoutError:
            failure_reason = "participant_timeout"
            await session.aclose()
            return

        await backend.activate(call_id)
        if not closed.done():
            try:
                await session.generate_reply(
                    instructions=context.greeting,
                    input_modality="audio",
                )
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
            extra={
                "call_session_id": str(call_id) if call_id is not None else None,
                "room": getattr(ctx.room, "name", None),
            },
        )
        failure_reason = "provider_session_error"
        if session is not None:
            await session.aclose()
    finally:
        if session is not None and persistence is not None:
            off = getattr(session, "off", None)
            if off is not None:
                off("conversation_item_added", persistence.on_conversation_item_added)
        try:
            if handed_off and persistence is not None and call_id is not None:
                conversation_complete = False
                try:
                    conversation_complete = await persistence.finish()
                except Exception:
                    logger.exception("conversation persistence drain failed")
                await backend.observe(
                    call_id,
                    "agent_relinquished",
                    conversation_status=(
                        "complete" if conversation_complete else "incomplete"
                    ),
                )
            elif terminalizer is not None:
                await terminalizer.terminalize(failure_reason)
            elif finalizer is not None and failure_reason is None:
                await finalizer.complete("incomplete")
            elif finalizer is not None:
                assert failure_reason is not None
                await finalizer.fail(failure_reason, "incomplete")
        finally:
            await backend.aclose()
            shutdown_voice_telemetry()
    if cancelled:
        raise asyncio.CancelledError


def log_terminalization_failure(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    if error := task.exception():
        logger.exception("Voice Agent terminalization failed", exc_info=error)


async def entrypoint(ctx: agents.JobContext) -> None:
    await run_job(ctx, VoiceAgentSettings())  # type: ignore[call-arg]


def build_server(settings: VoiceAgentSettings) -> agents.AgentServer:
    server = agents.AgentServer(
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key.get_secret_value(),
        api_secret=settings.livekit_api_secret.get_secret_value(),
        setup_fnc=setup_voice_telemetry,
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
