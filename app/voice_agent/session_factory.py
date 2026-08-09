import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from uuid import uuid4

from livekit.agents import Agent, AgentSession, RunContext, function_tool, llm, stt
from livekit.agents.beta import EndCallTool
from livekit.plugins import elevenlabs, openai

from app.voice_agent.backend_client import BackendCoreClient


logger = logging.getLogger(__name__)


async def execute_capability_with_announcement(
    *,
    context: RunContext,
    capability_name: str,
    tool_call_id: str,
    announcement: str | None,
    execute,
    telemetry,
):
    telemetry.emit(
        "tool_call_started",
        tool_call_id=tool_call_id,
        capability=capability_name,
        tool_name=capability_name,
    )
    telemetry.emit("announcement_configured", configured=bool(announcement))
    if announcement:
        telemetry.emit("announcement_started", capability=capability_name)
        speech = context.session.say(
            announcement,
            allow_interruptions=False,
            add_to_chat_ctx=False,
        )
        await speech
        telemetry.emit("announcement_completed", capability=capability_name)
    telemetry.emit("backend_request_started", capability=capability_name)
    try:
        result = await execute()
    except asyncio.CancelledError:
        raise
    except Exception:
        telemetry.emit("tool_call_failed", capability=capability_name)
        raise
    telemetry.emit(
        "tool_call_completed",
        tool_call_id=tool_call_id,
        capability=capability_name,
        status=result.get("status") if isinstance(result, dict) else None,
    )
    return result


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
            temperature=1,
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
            "preemptive_generation": {
                "enabled": turn.preemptive_generation.enabled,
                "preemptive_tts": False,
            },
        },
    )


def build_chat_context(metadata) -> llm.ChatContext:
    context = llm.ChatContext.empty()
    for message in metadata.chat_history:
        context.add_message(role=message.role, content=message.content)
    return context


@dataclass
class TurnCommitState:
    speech_id: str
    turn_id: str | None = None
    committed: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)

    def commit(self, turn_id: str) -> None:
        if not self.cancelled.is_set():
            self.turn_id = turn_id
            self.committed.set()

    def cancel(self) -> None:
        if not self.committed.is_set():
            self.cancelled.set()

    async def wait_until_committed_or_cancelled(self) -> bool:
        committed = asyncio.create_task(self.committed.wait())
        cancelled = asyncio.create_task(self.cancelled.wait())
        try:
            done, _ = await asyncio.wait(
                {committed, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            return committed in done and self.committed.is_set()
        finally:
            for task in (committed, cancelled):
                if not task.done():
                    task.cancel()
            await asyncio.gather(committed, cancelled, return_exceptions=True)


@dataclass
class VoiceTurnState:
    current_turn_id: str | None = None
    user_persistence: dict[str, asyncio.Task] = field(default_factory=dict)
    turns_by_speech: dict[str, TurnCommitState] = field(default_factory=dict)
    pending_speech_id: str | None = None
    pending_tool_calls: int = 0
    closed: bool = False

    def register_speech(self, speech_handle) -> None:
        if self.pending_speech_id:
            self.turns_by_speech[self.pending_speech_id].cancel()
        turn = TurnCommitState(speech_id=speech_handle.id)
        self.turns_by_speech[speech_handle.id] = turn
        self.pending_speech_id = speech_handle.id
        speech_handle.add_done_callback(
            lambda handle: self.cancel_speech(handle.id) if handle.interrupted else None
        )

    def commit_turn(self, turn_id: str) -> TurnCommitState | None:
        if self.closed or self.pending_speech_id is None:
            return None
        turn = self.turns_by_speech[self.pending_speech_id]
        turn.commit(turn_id)
        self.current_turn_id = turn_id
        return turn

    def cancel_speech(self, speech_id: str) -> None:
        if turn := self.turns_by_speech.get(speech_id):
            turn.cancel()

    def close(self) -> None:
        self.closed = True
        for turn in self.turns_by_speech.values():
            turn.cancel()


_END_CALL_INTENTS = (
    "nič viac",
    "nepotrebujem nič ďalšie",
    "nemám ďalšie otázky",
    "už nič",
    "to je všetko",
    "to bude všetko",
    "to je odo mňa všetko",
    "dovidenia",
    "zbohom",
    "ukončiť hovor",
    "ukončite hovor",
    "zložte",
    "nothing else",
    "don't need anything else",
    "no more questions",
    "that's all",
    "that is all",
    "goodbye",
    "bye",
    "end the call",
    "hang up",
)


class GuardedEndCallTool(EndCallTool):
    def __init__(self, state: VoiceTurnState):
        self._state = state
        super().__init__(
            ignore_on_enter=True,
            extra_description=(
                "Use only after a new, explicit user statement that they need nothing "
                "else, clearly say goodbye, or ask to end the call. Never use for an "
                "ambiguous acknowledgement such as 'dobre' or 'okay', in the same turn "
                "as another tool, while a tool is pending, before its result was spoken, "
                "or while a question remains unresolved."
            ),
            end_instructions=(
                "Give one short, natural farewell in the active conversation language. "
                "Do not add information or ask another question."
            ),
        )

    async def _end_call(self, ctx: RunContext):
        turn = self._state.turns_by_speech.get(ctx.speech_handle.id)
        if turn is None or not await turn.wait_until_committed_or_cancelled():
            return "The call remains active because the user's turn is not final."
        await asyncio.sleep(0)
        if self._state.pending_tool_calls:
            return "The call remains active because another tool is still running."
        last_user_message = next(
            (
                item.raw_text_content or ""
                for item in reversed(ctx.session.history.items)
                if getattr(item, "type", None) == "message"
                and getattr(item, "role", None) == "user"
            ),
            "",
        ).casefold()
        if not any(intent in last_user_message for intent in _END_CALL_INTENTS):
            return "The call remains active because the user did not clearly end it."
        return await super()._end_call(ctx)


def build_human_handoff_tool(execute, state: VoiceTurnState, telemetry):
    async def runtime_tool(
        context: RunContext, raw_arguments: dict[str, object]
    ) -> str:
        turn = state.turns_by_speech.get(context.speech_handle.id)
        if turn is None or not await turn.wait_until_committed_or_cancelled():
            return "Human handoff was not started because the user's turn is not final."
        if state.closed or context.speech_handle.interrupted:
            return "Human handoff was cancelled."
        if state.pending_tool_calls:
            return "Human handoff was not started because another tool is still running."
        return await execute_capability_with_announcement(
            context=context,
            capability_name="human_handoff",
            tool_call_id=context.function_call.call_id,
            announcement="Prepojím vás s pracovníkom recepcie. Prosím, zostaňte na linke.",
            execute=lambda: execute(context),
            telemetry=telemetry,
        )

    return function_tool(
        runtime_tool,
        raw_schema={
            "name": "human_handoff",
            "description": (
                "Connect the caller to a human receptionist when the caller explicitly "
                "asks to speak with a person. Use only for a direct human-connection "
                "request, not for ordinary questions or unresolved tool work."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    )


def build_function_tools(
    metadata, backend: BackendCoreClient, state: VoiceTurnState, telemetry, caller_number=None
):
    async def _execute(context: RunContext, definition, arguments: dict):
        capability = definition.backend_capability
        turn = state.turns_by_speech.get(context.speech_handle.id)
        waited_for_commit = bool(turn and not turn.committed.is_set()) or bool(
            getattr(telemetry, "preemptive_generation_used", False)
        )
        if waited_for_commit:
            telemetry.emit(
                "tool_waiting_for_commit",
                tool_call_id=context.function_call.call_id,
                capability=capability,
            )
        if turn is None or not await turn.wait_until_committed_or_cancelled():
            telemetry.emit(
                "tool_cancelled_before_commit",
                tool_call_id=context.function_call.call_id,
                capability=capability,
            )
            raise asyncio.CancelledError
        turn_id = turn.turn_id
        if turn_id is None or state.closed or context.speech_handle.interrupted:
            raise asyncio.CancelledError
        telemetry.mark_preemptive_reused(tool_waited=waited_for_commit)
        if waited_for_commit:
            telemetry.emit(
                "tool_released_after_commit",
                tool_call_id=context.function_call.call_id,
                capability=capability,
            )
        if task := state.user_persistence.get(turn_id):
            await task
        if state.closed or context.speech_handle.interrupted:
            raise asyncio.CancelledError

        if "use_inbound_caller_number" in definition.parameters.get("properties", {}):
            use_inbound = arguments.pop("use_inbound_caller_number", False)
            if use_inbound and not caller_number:
                return {
                    "status": "skipped",
                    "message": "Trusted inbound caller number is unavailable.",
                    "error": "inbound_caller_number_unavailable",
                }
            if use_inbound:
                arguments["reservation_phone"] = caller_number

        if definition.argument_container:
            arguments = {definition.argument_container: arguments}
        if definition.inject_caller_number:
            arguments = {**arguments, "caller_number": caller_number}

        telemetry.set_turn_kind("tool_call")

        async def call_backend() -> dict:
            return await backend.execute_tool(
                capability=capability,
                arguments=arguments,
                turn_id=turn_id,
                tool_call_id=context.function_call.call_id,
            )

        try:
            return await execute_capability_with_announcement(
                context=context,
                capability_name=capability,
                tool_call_id=context.function_call.call_id,
                announcement=definition.announcement,
                execute=call_backend,
                telemetry=telemetry,
            )
        except Exception as exc:
            logger.exception("Backend Core tool call failed")
            return {"status": "failed", "error": str(exc)}

    async def execute(context: RunContext, definition, arguments: dict):
        state.pending_tool_calls += 1
        try:
            return await _execute(context, definition, arguments)
        finally:
            state.pending_tool_calls -= 1

    def build(definition):
        async def runtime_tool(
            context: RunContext, raw_arguments: dict[str, object]
        ) -> dict:
            return await execute(context, definition, dict(raw_arguments))

        return function_tool(
            runtime_tool,
            raw_schema={
                "name": definition.public_name,
                "description": definition.description,
                "parameters": definition.parameters,
            },
        )

    return [build(definition) for definition in metadata.tools if definition.enabled]


class HospitalityAgent(Agent):
    def __init__(
        self,
        metadata,
        backend: BackendCoreClient,
        telemetry,
        state: VoiceTurnState,
        caller_number=None,
        human_handoff=None,
    ):
        tools: list[llm.Tool | llm.Toolset] = list(
            build_function_tools(metadata, backend, state, telemetry, caller_number)
        )
        if metadata.end_call_enabled:
            tools.append(GuardedEndCallTool(state))
        caller_instructions = ""
        if human_handoff:
            tools.append(build_human_handoff_tool(human_handoff, state, telemetry))
            caller_instructions = (
                "\n\nHuman handoff is available. If the caller explicitly asks to speak "
                "with a person, use the human_handoff tool. This runtime instruction "
                "supersedes older tenant text saying that human transfer is unavailable."
            )
        if any(
            "use_inbound_caller_number" in tool.parameters.get("properties", {})
            for tool in metadata.tools
        ):
            caller_instructions += (
                "\n\nA trusted inbound caller number is available: "
                f"{caller_number}. Set use_inbound_caller_number to true only after the guest "
                "consents under the tenant contact policy."
                if caller_number
                else "\n\nNo trusted inbound caller number is available. "
                "Set use_inbound_caller_number to false."
            )
        super().__init__(
            instructions=metadata.instructions + caller_instructions,
            chat_ctx=build_chat_context(metadata),
            tools=tools,
        )
        self.backend = backend
        self.telemetry = telemetry
        self.state = state

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        self.telemetry.mark_turn_committed()

    def accept_user_message(self, new_message) -> None:
        if new_message.id in self.state.user_persistence:
            return
        if self.state.commit_turn(new_message.id) is None:
            logger.error("Cannot persist voice turn without a LiveKit speech handle")
            return
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
        attempt = self.telemetry.mark_llm_started()
        try:
            stream = Agent.default.llm_node(self, chat_ctx, tools, model_settings)
            if inspect.isawaitable(stream):
                stream = await stream
            first = True
            async for chunk in stream:
                if first:
                    first = False
                    self.telemetry.mark_llm_first_chunk(attempt)
                yield chunk
            self.telemetry.emit("llm_completed")
        except asyncio.CancelledError:
            self.telemetry.mark_preemptive_cancelled(attempt)
            raise

    async def tts_node(self, text, model_settings):
        self.telemetry.mark_preemptive_reused()
        self.telemetry.emit("tts_started")
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
