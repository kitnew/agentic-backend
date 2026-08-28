"""Process-owned, privacy-safe OpenTelemetry for LiveKit job processes."""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import os
import time
from collections.abc import AsyncGenerator, AsyncIterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from agentic_observability.attributes import metric_attributes
from agentic_observability.bootstrap import TelemetryProviders, bootstrap
from agentic_observability.config import TelemetryConfig
from agentic_observability.logging import install_trace_context_filter
from livekit import agents, rtc
from livekit.agents import llm
from livekit.agents.telemetry import set_tracer_provider
from livekit.agents.types import USERDATA_TTS_STARTED_TIME, FlushSentinel
from livekit.agents.voice.agent import ModelSettings
from livekit.agents.voice.agent_activity import _SpeechHandleContextVar
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
from opentelemetry.sdk.util import BoundedList
from opentelemetry.trace import Status

_runtime: VoiceTelemetryRuntime | None = None
_MAX_PIPELINE_TRACKERS = 128


@dataclass(slots=True)
class _PipelineLatency:
    llm_request_started: float
    llm_first_nonempty_text: float | None = None


@dataclass(slots=True)
class _EotTurn:
    local_vad_end: float | None = None
    stt_final_received: float | None = None
    stt_eos_received: float | None = None
    livekit_turn_committed: float | None = None
    on_user_turn_completed_started: float | None = None
    llm_request_started: float | None = None
    observed: set[str] = field(default_factory=set)


class LiveKitPrivacySpanProcessor(SpanProcessor):
    """Remove conversational content from native LiveKit spans before export."""

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        scope = span.instrumentation_scope
        if scope is None or scope.name != "livekit-agents":
            return
        attributes: Any = span._attributes  # type: ignore[attr-defined]
        if attributes is not None:
            for key in list(attributes):
                if _is_private_livekit_attribute(str(key)):
                    del attributes[key]
        span._events = BoundedList(maxlen=0)  # type: ignore[attr-defined]
        span._status = Status(span.status.status_code)  # type: ignore[attr-defined]

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def _is_private_livekit_attribute(key: str) -> bool:
    # Native LiveKit attributes include chat contexts, transcripts, tool payloads,
    # provider request ids, and session metadata. Metrics are sourced separately.
    return key.startswith(("lk.", "gen_ai.")) or key in {
        "exception.message",
        "exception.stacktrace",
    }


@dataclass
class VoiceMetrics:
    _meter: Any

    def __post_init__(self) -> None:
        self._turn_transcription_delay = self._meter.create_histogram(
            "voice.turn.transcription_delay", unit="s"
        )
        self._turn_end_of_turn_delay = self._meter.create_histogram(
            "voice.turn.end_of_turn_delay", unit="s"
        )
        self._turn_user_completed_delay = self._meter.create_histogram(
            "voice.turn.on_user_turn_completed_delay", unit="s"
        )
        self._turn_llm_ttft = self._meter.create_histogram(
            "voice.turn.llm_ttft", unit="s"
        )
        self._turn_llm_usable_ttft = self._meter.create_histogram(
            "voice.turn.llm_usable_ttft", unit="s"
        )
        self._turn_llm_to_tts_dispatch_latency = self._meter.create_histogram(
            "voice.turn.llm_to_tts_dispatch_latency", unit="s"
        )
        self._turn_tts_ttfb = self._meter.create_histogram(
            "voice.turn.tts_ttfb", unit="s"
        )
        self._turn_tts_effective_first_audio_latency = self._meter.create_histogram(
            "voice.turn.tts_effective_first_audio_latency", unit="s"
        )
        self._turn_playback_latency = self._meter.create_histogram(
            "voice.turn.playback_latency", unit="s"
        )
        self._turn_e2e_latency = self._meter.create_histogram(
            "voice.turn.e2e_latency", unit="s"
        )
        self._eot_local_vad_to_stt_final = self._meter.create_histogram(
            "voice.turn.eot.local_vad_to_stt_final", unit="s"
        )
        self._eot_stt_final_to_stt_eos = self._meter.create_histogram(
            "voice.turn.eot.stt_final_to_stt_eos", unit="s"
        )
        self._eot_stt_eos_to_turn_commit = self._meter.create_histogram(
            "voice.turn.eot.stt_eos_to_turn_commit", unit="s"
        )
        self._eot_turn_commit_to_user_completed = self._meter.create_histogram(
            "voice.turn.eot.turn_commit_to_user_completed", unit="s"
        )
        self._eot_turn_commit_to_llm_request = self._meter.create_histogram(
            "voice.turn.eot.turn_commit_to_llm_request", unit="s"
        )
        self._eot_local_vad_to_turn_commit = self._meter.create_histogram(
            "voice.turn.eot.local_vad_to_turn_commit", unit="s"
        )
        self._llm_requests = self._meter.create_counter("voice.llm.requests")
        self._llm_duration = self._meter.create_histogram(
            "voice.llm.duration", unit="s"
        )
        self._llm_ttft = self._meter.create_histogram("voice.llm.ttft", unit="s")
        self._llm_input_tokens = self._meter.create_counter("voice.llm.input_tokens")
        self._llm_cached_tokens = self._meter.create_counter(
            "voice.llm.input_cached_tokens"
        )
        self._llm_output_tokens = self._meter.create_counter("voice.llm.output_tokens")
        self._stt_requests = self._meter.create_counter("voice.stt.requests")
        self._stt_duration = self._meter.create_histogram(
            "voice.stt.duration", unit="s"
        )
        self._stt_audio_duration = self._meter.create_counter(
            "voice.stt.audio_duration", unit="s"
        )
        self._tts_requests = self._meter.create_counter("voice.tts.requests")
        self._tts_duration = self._meter.create_histogram(
            "voice.tts.duration", unit="s"
        )
        self._tts_ttfb = self._meter.create_histogram("voice.tts.ttfb", unit="s")
        self._tts_audio_duration = self._meter.create_counter(
            "voice.tts.audio_duration", unit="s"
        )
        self._tts_characters = self._meter.create_counter("voice.tts.characters")
        self._tts_connection_acquire_time = self._meter.create_histogram(
            "voice.tts.connection.acquire_time", unit="s"
        )
        self._tts_connection_requests = self._meter.create_counter(
            "voice.tts.connection.requests", unit="{request}"
        )
        self._speculative_started = self._meter.create_counter(
            "voice.speculative_generation.started", unit="{generation}"
        )
        self._speculative_reused = self._meter.create_counter(
            "voice.speculative_generation.reused", unit="{generation}"
        )
        self._speculative_cancelled = self._meter.create_counter(
            "voice.speculative_generation.cancelled", unit="{generation}"
        )
        self._speculative_lead_time = self._meter.create_histogram(
            "voice.speculative_generation.lead_time", unit="s"
        )
        self._errors = self._meter.create_counter("voice.component.errors")
        self._capability_executions = self._meter.create_counter(
            "capability.executions"
        )
        self._capability_failures = self._meter.create_counter("capability.failures")
        self._capability_duration = self._meter.create_histogram(
            "capability.execution.duration", unit="s"
        )
        self._pipeline_latency: dict[str, _PipelineLatency] = {}
        self._eot_turns: list[_EotTurn] = []

    def attach_eot_decomposition(self, session: agents.AgentSession) -> None:
        _install_eot_hooks(session, self)

    def record_local_vad_end(self, timestamp: float) -> None:
        turn = self._active_eot_turn()
        turn.local_vad_end = timestamp
        self._observe_eot(turn)

    def record_stt_final_received(self, timestamp: float) -> None:
        turn = self._active_eot_turn()
        if turn.stt_eos_received is None:
            turn.stt_final_received = timestamp
        self._observe_eot(turn)

    def record_stt_eos_received(self, timestamp: float) -> None:
        turn = self._active_eot_turn()
        if turn.stt_eos_received is None:
            turn.stt_eos_received = timestamp
        self._observe_eot(turn)

    def record_livekit_turn_committed(self, timestamp: float) -> None:
        turn = self._active_eot_turn()
        if turn.livekit_turn_committed is None:
            turn.livekit_turn_committed = timestamp
        self._observe_eot(turn)

    def record_on_user_turn_completed_started(self, timestamp: float) -> None:
        turn = next(
            (
                item
                for item in self._eot_turns
                if item.livekit_turn_committed is not None
                and item.on_user_turn_completed_started is None
            ),
            None,
        )
        if turn is not None:
            turn.on_user_turn_completed_started = timestamp
            self._observe_eot(turn)

    def _active_eot_turn(self) -> _EotTurn:
        if self._eot_turns and self._eot_turns[-1].livekit_turn_committed is None:
            return self._eot_turns[-1]
        if len(self._eot_turns) >= _MAX_PIPELINE_TRACKERS:
            self._eot_turns.pop(0)
        turn = _EotTurn()
        self._eot_turns.append(turn)
        return turn

    def _observe_eot(self, turn: _EotTurn) -> None:
        for name, instrument, start, end in (
            (
                "local_vad_to_stt_final",
                self._eot_local_vad_to_stt_final,
                turn.local_vad_end,
                turn.stt_final_received,
            ),
            (
                "stt_final_to_stt_eos",
                self._eot_stt_final_to_stt_eos,
                turn.stt_final_received,
                turn.stt_eos_received,
            ),
            (
                "stt_eos_to_turn_commit",
                self._eot_stt_eos_to_turn_commit,
                turn.stt_eos_received,
                turn.livekit_turn_committed,
            ),
            (
                "turn_commit_to_user_completed",
                self._eot_turn_commit_to_user_completed,
                turn.livekit_turn_committed,
                turn.on_user_turn_completed_started,
            ),
            (
                "turn_commit_to_llm_request",
                self._eot_turn_commit_to_llm_request,
                turn.livekit_turn_committed,
                turn.llm_request_started,
            ),
            (
                "local_vad_to_turn_commit",
                self._eot_local_vad_to_turn_commit,
                turn.local_vad_end,
                turn.livekit_turn_committed,
            ),
        ):
            if (
                name not in turn.observed
                and start is not None
                and end is not None
                and end >= start
            ):
                self._record(instrument, end - start, {})
                turn.observed.add(name)

    def attach_speculative_generation(self, session: agents.AgentSession) -> None:
        awaiting_speculative_speech = False
        active_speculation: dict[str, Any] | None = None
        last_interim_text: str | None = None

        def clear_pending() -> None:
            nonlocal awaiting_speculative_speech
            awaiting_speculative_speech = False

        def on_transcript(event: object) -> None:
            nonlocal awaiting_speculative_speech, last_interim_text
            if getattr(event, "is_final", True):
                value = getattr(event, "transcript", None)
                if (
                    active_speculation is not None
                    and not active_speculation["resolved"]
                ):
                    active_speculation["final_seen"] = True
                    active_speculation["final_text"] = (
                        value if isinstance(value, str) else None
                    )
                return
            value = getattr(event, "transcript", None)
            last_interim_text = value if isinstance(value, str) else None
            awaiting_speculative_speech = True
            asyncio.get_running_loop().call_soon(clear_pending)

        def on_speech_created(event: object) -> None:
            nonlocal awaiting_speculative_speech, active_speculation
            if not awaiting_speculative_speech:
                return
            if getattr(event, "source", None) != "generate_reply":
                return
            awaiting_speculative_speech = False
            handle = getattr(event, "speech_handle", None)
            scheduled_fut = getattr(handle, "_scheduled_fut", None)
            if handle is None or not isinstance(scheduled_fut, asyncio.Future):
                return

            if active_speculation is not None and not active_speculation["resolved"]:
                active_speculation["reason"] = "superseded_interim"

            started_at = time.perf_counter()
            resolved = False
            observation: dict[str, Any] = {
                "resolved": False,
                "reason": None,
                "candidate": last_interim_text,
                "final_seen": False,
                "final_text": None,
            }
            active_speculation = observation
            self._add(self._speculative_started, 1, {})

            def on_scheduled(_: asyncio.Future[None]) -> None:
                nonlocal resolved
                if resolved or not handle.scheduled:
                    return
                resolved = True
                observation["resolved"] = True
                self._add(self._speculative_reused, 1, {})
                self._record(
                    self._speculative_lead_time,
                    time.perf_counter() - started_at,
                    {},
                )

            def on_done(_: object) -> None:
                nonlocal resolved
                if resolved or handle.scheduled:
                    return
                resolved = True
                reason = observation["reason"]
                if reason is None and observation["final_seen"]:
                    candidate = observation["candidate"]
                    final_text = observation["final_text"]
                    reason = (
                        "final_transcript_mismatch"
                        if isinstance(candidate, str)
                        and isinstance(final_text, str)
                        and candidate != final_text
                        else "context_tools_or_tool_choice_mismatch"
                    )
                if reason is None:
                    reason = "interrupted_or_shutdown"
                observation["resolved"] = True
                self._add(self._speculative_cancelled, 1, {"reason": reason})

            scheduled_fut.add_done_callback(on_scheduled)
            handle.add_done_callback(on_done)

        session.on("user_input_transcribed", on_transcript)
        session.on("speech_created", on_speech_created)

    def record_turn(self, item: object) -> None:
        values = getattr(item, "metrics", None)
        if not isinstance(values, Mapping):
            return
        self._record(
            self._turn_transcription_delay,
            values.get("transcription_delay"),
            _turn_attrs(values, "stt_metadata"),
        )
        self._record(
            self._turn_end_of_turn_delay,
            values.get("end_of_turn_delay"),
            _turn_attrs(values, "stt_metadata"),
        )
        self._record(
            self._turn_user_completed_delay,
            values.get("on_user_turn_completed_delay"),
            _turn_attrs(values, "stt_metadata"),
        )
        self._record(
            self._turn_llm_ttft,
            values.get("llm_node_ttft"),
            _turn_attrs(values, "llm_metadata"),
        )
        self._record(
            self._turn_tts_ttfb,
            values.get("tts_node_ttfb"),
            _turn_attrs(values, "tts_metadata"),
        )
        self._record(
            self._turn_e2e_latency,
            values.get("e2e_latency"),
            _turn_attrs(values, "llm_metadata"),
        )
        self._record(
            self._turn_playback_latency,
            values.get("playback_latency"),
            _turn_attrs(values, "tts_metadata"),
        )

    def record_component_metric(self, metric: object) -> None:
        kind = getattr(metric, "type", None)
        if kind == "llm_metrics":
            attributes = _component_attrs("llm", metric)
            attributes["status"] = (
                "cancelled" if getattr(metric, "cancelled", False) else "ok"
            )
            self._add(self._llm_requests, 1, attributes)
            self._record(
                self._llm_duration, getattr(metric, "duration", None), attributes
            )
            self._record(self._llm_ttft, getattr(metric, "ttft", None), attributes)
            self._add(
                self._llm_input_tokens, getattr(metric, "prompt_tokens", 0), attributes
            )
            self._add(
                self._llm_cached_tokens,
                getattr(metric, "prompt_cached_tokens", 0),
                attributes,
            )
            self._add(
                self._llm_output_tokens,
                getattr(metric, "completion_tokens", 0),
                attributes,
            )
        elif kind == "stt_metrics":
            attributes = _component_attrs("stt", metric)
            self._add(self._stt_requests, 1, attributes)
            if not getattr(metric, "streamed", False):
                self._record(
                    self._stt_duration, getattr(metric, "duration", None), attributes
                )
            self._add(
                self._stt_audio_duration,
                getattr(metric, "audio_duration", 0),
                attributes,
            )
        elif kind == "tts_metrics":
            attributes = _component_attrs("tts", metric)
            attributes["status"] = (
                "cancelled" if getattr(metric, "cancelled", False) else "ok"
            )
            self._add(self._tts_requests, 1, attributes)
            self._record(
                self._tts_duration, getattr(metric, "duration", None), attributes
            )
            self._record(self._tts_ttfb, getattr(metric, "ttfb", None), attributes)
            self._add(
                self._tts_audio_duration,
                getattr(metric, "audio_duration", 0),
                attributes,
            )
            self._add(
                self._tts_characters,
                getattr(metric, "characters_count", 0),
                attributes,
            )
            self._record(
                self._tts_connection_acquire_time,
                getattr(metric, "acquire_time", None),
                attributes,
            )
            connection_reused = getattr(metric, "connection_reused", None)
            if isinstance(connection_reused, bool):
                self._add(
                    self._tts_connection_requests,
                    1,
                    {**attributes, "outcome": "reused" if connection_reused else "new"},
                )

    def record_llm_request_started(self, speech_id: str, timestamp: float) -> None:
        turn = (
            self._eot_turns[-1]
            if self._eot_turns
            and self._eot_turns[-1].livekit_turn_committed is None
            and self._eot_turns[-1].llm_request_started is None
            else next(
                (
                    item
                    for item in self._eot_turns
                    if item.livekit_turn_committed is not None
                    and item.on_user_turn_completed_started is not None
                    and (
                        item.llm_request_started is None
                        or item.llm_request_started < item.livekit_turn_committed
                    )
                ),
                None,
            )
        )
        if turn is not None:
            turn.llm_request_started = timestamp
            self._observe_eot(turn)
        if speech_id in self._pipeline_latency:
            return
        if len(self._pipeline_latency) >= _MAX_PIPELINE_TRACKERS:
            self._pipeline_latency.pop(next(iter(self._pipeline_latency)))
        self._pipeline_latency[speech_id] = _PipelineLatency(timestamp)

    def record_llm_first_nonempty_text(self, speech_id: str, timestamp: float) -> None:
        timing = self._pipeline_latency.get(speech_id)
        if timing is not None and timing.llm_first_nonempty_text is None:
            timing.llm_first_nonempty_text = timestamp

    def record_tts_first_audio(
        self,
        speech_id: str,
        *,
        tts_first_text_sent: float,
        tts_first_audio: float,
    ) -> None:
        timing = self._pipeline_latency.pop(speech_id, None)
        if timing is None or timing.llm_first_nonempty_text is None:
            return
        if not (
            timing.llm_request_started
            <= timing.llm_first_nonempty_text
            <= tts_first_text_sent
            <= tts_first_audio
        ):
            return
        self._record(
            self._turn_llm_usable_ttft,
            timing.llm_first_nonempty_text - timing.llm_request_started,
            {},
        )
        self._record(
            self._turn_llm_to_tts_dispatch_latency,
            tts_first_text_sent - timing.llm_first_nonempty_text,
            {},
        )
        self._record(
            self._turn_tts_effective_first_audio_latency,
            tts_first_audio - tts_first_text_sent,
            {},
        )

    def record_component_error(self, component: str, error: object) -> None:
        self._add(
            self._errors,
            1,
            {
                "voice.component": component,
                "error.type": type(error).__name__,
                "status": "error",
            },
        )

    def record_capability_execution(
        self,
        *,
        name: str,
        version: str,
        status: str,
        duration_seconds: float,
        error_type: str | None = None,
    ) -> None:
        attributes = {
            "capability.name": name,
            "capability.version": version,
            "status": status,
        }
        if error_type is not None:
            attributes["error.type"] = error_type
        metric_attributes(attributes)
        self._capability_executions.add(1, attributes)
        self._capability_duration.record(duration_seconds, attributes)
        if status == "failed":
            self._capability_failures.add(1, attributes)

    def _record(
        self, instrument: Any, value: object, attributes: dict[str, str]
    ) -> None:
        if (measurement := _measurement(value)) is not None:
            instrument.record(measurement, attributes=metric_attributes(attributes))

    def _add(self, instrument: Any, value: object, attributes: dict[str, str]) -> None:
        if (measurement := _measurement(value)) and measurement > 0:
            instrument.add(measurement, attributes=metric_attributes(attributes))


def _measurement(value: object) -> float | None:
    if isinstance(value, int | float) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def record_capability_execution(
    *,
    name: str,
    version: str,
    status: str,
    duration_seconds: float,
    error_type: str | None = None,
) -> None:
    runtime = current_voice_telemetry()
    if runtime is not None:
        runtime.metrics.record_capability_execution(
            name=name,
            version=version,
            status=status,
            duration_seconds=duration_seconds,
            error_type=error_type,
        )


def _component_attrs(component: str, metric: object) -> dict[str, str]:
    attributes = {"voice.component": component}
    metadata = getattr(metric, "metadata", None)
    provider = getattr(metadata, "model_provider", None)
    model = getattr(metadata, "model_name", None)
    if isinstance(provider, str) and provider:
        attributes["voice.provider"] = provider
    if isinstance(model, str) and model:
        attributes["voice.model"] = model
    return attributes


def _turn_attrs(values: Mapping[str, object], metadata_name: str) -> dict[str, str]:
    metadata = values.get(metadata_name)
    if not isinstance(metadata, Mapping):
        return {}
    attributes: dict[str, str] = {}
    for source, target in (
        ("model_provider", "voice.provider"),
        ("model_name", "voice.model"),
    ):
        value = metadata.get(source)
        if isinstance(value, str) and value:
            attributes[target] = value
    return attributes


class LatencyInstrumentedAgent(agents.Agent):
    def __init__(self, *, metrics: VoiceMetrics | None, **kwargs: Any) -> None:
        kwargs.setdefault("id", "default_agent")
        super().__init__(**kwargs)
        self._voice_metrics = metrics

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        if self._voice_metrics is not None:
            self._voice_metrics.record_on_user_turn_completed_started(
                time.perf_counter()
            )
        await super().on_user_turn_completed(turn_ctx, new_message)

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[llm.ChatChunk | str | FlushSentinel]:
        speech_id = _current_speech_id()
        if self._voice_metrics is not None and speech_id is not None:
            self._voice_metrics.record_llm_request_started(
                speech_id, time.perf_counter()
            )
        raw_output = super().llm_node(chat_ctx, tools, model_settings)
        if inspect.isawaitable(raw_output):
            output = await raw_output
        else:
            output = raw_output
        if not isinstance(output, AsyncIterable):
            return
        async for chunk in output:
            delta = getattr(chunk, "delta", None)
            content = (
                chunk if isinstance(chunk, str) else getattr(delta, "content", None)
            )
            if (
                self._voice_metrics is not None
                and speech_id is not None
                and isinstance(content, str)
                and content.strip()
            ):
                self._voice_metrics.record_llm_first_nonempty_text(
                    speech_id, time.perf_counter()
                )
            yield chunk

    async def tts_node(
        self,
        text: AsyncIterable[str],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[rtc.AudioFrame]:
        speech_id = _current_speech_id()
        first_audio = True
        raw_output = super().tts_node(text, model_settings)
        if inspect.isawaitable(raw_output):
            output = await raw_output
        else:
            output = raw_output
        if not isinstance(output, AsyncIterable):
            return
        async for frame in output:
            if (
                self._voice_metrics is not None
                and speech_id is not None
                and first_audio
            ):
                first_audio = False
                tts_first_text_sent = frame.userdata.get(USERDATA_TTS_STARTED_TIME)
                if isinstance(tts_first_text_sent, int | float):
                    self._voice_metrics.record_tts_first_audio(
                        speech_id,
                        tts_first_text_sent=float(tts_first_text_sent),
                        tts_first_audio=time.perf_counter(),
                    )
            yield frame


def _current_speech_id() -> str | None:
    # Reuse the pinned SDK's own context used to attach speech_id to LLM/TTS metrics.
    speech = _SpeechHandleContextVar.get(None)
    return speech.id if speech is not None else None


def _install_eot_hooks(session: agents.AgentSession, metrics: VoiceMetrics) -> None:
    """Attach to the pinned 1.6.7 recognition boundary missing from public events."""
    activity = getattr(session, "_activity", None)
    required = ("on_end_of_speech", "on_final_transcript", "on_end_of_turn")
    if activity is None or not all(
        callable(getattr(activity, name, None)) for name in required
    ):
        raise RuntimeError("LiveKit 1.6.7 recognition hooks are unavailable")

    on_end_of_speech = activity.on_end_of_speech
    on_final_transcript = activity.on_final_transcript
    on_end_of_turn = activity.on_end_of_turn

    def instrumented_end_of_speech(event: object | None) -> None:
        timestamp = time.perf_counter()
        if event is None:
            metrics.record_stt_eos_received(timestamp)
        else:
            metrics.record_local_vad_end(timestamp)
        on_end_of_speech(event)

    def instrumented_final_transcript(
        event: object, *, speaking: bool | None = None
    ) -> None:
        metrics.record_stt_final_received(time.perf_counter())
        on_final_transcript(event, speaking=speaking)

    def instrumented_end_of_turn(info: object) -> bool:
        committed = on_end_of_turn(info)
        if committed:
            metrics.record_livekit_turn_committed(time.perf_counter())
        return committed

    activity.on_end_of_speech = instrumented_end_of_speech
    activity.on_final_transcript = instrumented_final_transcript
    activity.on_end_of_turn = instrumented_end_of_turn


@dataclass(slots=True)
class VoiceTelemetryRuntime:
    providers: TelemetryProviders
    metrics: VoiceMetrics

    def set_session_correlation(self, call_id: UUID) -> None:
        span = trace.get_current_span()
        if span.get_span_context().is_valid:
            span.set_attribute("call.id", str(call_id))


def setup_voice_telemetry(_: agents.JobProcess) -> None:
    if _runtime is not None or os.getenv("OTEL_ENABLED", "").lower() != "true":
        return
    environ = {**os.environ, "OTEL_SERVICE_NAME": "voice-agent"}
    providers = bootstrap(
        TelemetryConfig.from_env(default_service_name="voice-agent", environ=environ),
        span_processors=(LiveKitPrivacySpanProcessor(),),
    )
    configure_voice_telemetry(providers)


def configure_voice_telemetry(
    providers: TelemetryProviders,
) -> VoiceTelemetryRuntime | None:
    global _runtime
    if _runtime is not None:
        return _runtime
    if providers.tracer_provider is None or providers.meter_provider is None:
        return None
    set_tracer_provider(providers.tracer_provider)  # type: ignore[arg-type]
    meter = providers.meter("voice-agent")
    if meter is None:
        return None
    install_trace_context_filter(logging.getLogger().handlers)
    _runtime = VoiceTelemetryRuntime(providers, VoiceMetrics(meter))
    return _runtime


def current_voice_telemetry() -> VoiceTelemetryRuntime | None:
    return _runtime


def shutdown_voice_telemetry() -> None:
    global _runtime
    if _runtime is None:
        return
    runtime = _runtime
    _runtime = None
    runtime.providers.shutdown()
