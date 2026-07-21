import asyncio
import json
import logging
import time
from datetime import datetime, timezone


logger = logging.getLogger("voice_agent.telemetry")


class VoiceTelemetry:
    def __init__(self, identifiers: dict[str, str], publisher=None, configuration=None):
        self.identifiers = identifiers
        self.publisher = publisher
        self.configuration = configuration
        self.marks: dict[str, float] = {}
        self.turn_id: str | None = None
        self.response_id: str | None = None
        self.speech_id: str | None = None
        self.agent_state = "initializing"
        self.turn_kind = "direct_response"
        self.interrupted = False
        self.preemptive_generation_enabled = bool(
            configuration and configuration.preemptive_generation.enabled
        )
        self.preemptive_generation_used = False
        self.preemptive_response_reused = False
        self.preemptive_response_cancelled = False
        self.tool_waited_for_commit = False
        self._preemptive_attempt = 0
        self.recorded_durations: dict[str, float] = {}
        self._traced_turns: set[tuple[str | None, str | None]] = set()
        self._tasks: set[asyncio.Task] = set()

    def begin_turn(self, turn_id: str, response_id: str) -> None:
        if turn_id != self.turn_id:
            self.marks = {
                key: value
                for key, value in self.marks.items()
                if key in {
                    "speech_started", "speech_ended", "first_interim_transcript",
                    "final_transcript", "turn_committed", "preemptive_llm_started",
                    "preemptive_llm_first_chunk", "preemptive_response_reused",
                    "preemptive_response_cancelled",
                }
            }
            self.turn_kind = "direct_response"
            self.interrupted = False
            self.recorded_durations = {}
        self.turn_id, self.response_id = turn_id, response_id

    def mark_turn_committed(self) -> None:
        self.emit("turn_committed")

    def mark_llm_started(self) -> int | None:
        self.emit("llm_request_started")
        if not self.preemptive_generation_enabled or "turn_committed" in self.marks:
            return None
        self._preemptive_attempt += 1
        self.preemptive_generation_used = True
        self.emit("preemptive_candidate_ready", attempt=self._preemptive_attempt)
        self.emit("preemptive_llm_started", attempt=self._preemptive_attempt)
        return self._preemptive_attempt

    def mark_llm_first_chunk(self, attempt: int | None) -> None:
        self.emit("llm_first_chunk")
        if attempt == self._preemptive_attempt:
            self.emit("preemptive_llm_first_chunk", attempt=attempt)

    def mark_preemptive_cancelled(self, attempt: int | None) -> None:
        if attempt is None:
            return
        self.preemptive_response_cancelled = True
        self.emit("preemptive_response_cancelled", attempt=attempt)
        self.emit("preemptive_response_discarded", attempt=attempt)

    def mark_preemptive_reused(self, *, tool_waited: bool = False) -> None:
        self.tool_waited_for_commit |= tool_waited
        if (
            not self.preemptive_generation_used
            or self.preemptive_response_reused
            or "turn_committed" not in self.marks
        ):
            return
        self.preemptive_response_reused = True
        self.emit("preemptive_response_reused")

    def set_turn_kind(self, value: str) -> None:
        self.turn_kind = value

    def record_duration(self, name: str, value: float | None) -> None:
        if value is not None and value >= 0:
            self.recorded_durations[name] = round(value, 1)

    def emit(self, event: str, **fields) -> dict:
        now = time.monotonic()
        if event == "speech_started":
            self.marks.clear()
            if self.agent_state != "speaking":
                self.turn_id = self.response_id = self.speech_id = None
            self._traced_turns.discard((None, None))
            self.preemptive_generation_used = False
            self.preemptive_response_reused = False
            self.preemptive_response_cancelled = False
            self.tool_waited_for_commit = False
        if fields.get("speech_id"):
            self.speech_id = fields["speech_id"]
        self.marks[event] = now
        payload = {
            **self.identifiers,
            "turn_id": self.turn_id,
            "response_id": self.response_id,
            "speech_id": self.speech_id,
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
            **self._durations(event, now),
        }
        if event == "agent_playback_stopped":
            self.marks.pop("interruption_detected", None)
        logger.info("%s", json.dumps(payload, separators=(",", ":"), default=str))
        if self.publisher:
            task = asyncio.create_task(self.publisher(payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        if event == "error":
            self.turn_kind = "error"
            self.emit_trace()
        elif event == "session_closed" and self.marks:
            self.emit_trace()
        return payload

    def bind_session(self, session, on_user_speech_started=None) -> None:
        @session.on("user_state_changed")
        def on_user_state(event):
            if event.new_state == "speaking":
                if on_user_speech_started:
                    on_user_speech_started()
                self.emit("speech_started")
                if self.agent_state == "speaking":
                    self.interrupted = True
                    self.emit("interruption_detected")
            elif event.old_state == "speaking":
                self.emit("speech_ended")

        @session.on("user_input_transcribed")
        def on_transcript(event):
            if event.is_final:
                self.emit("final_transcript")
            elif "first_interim_transcript" not in self.marks:
                self.emit("first_interim_transcript")

        @session.on("speech_created")
        def on_speech(event):
            if event.source == "generate_reply":
                self.emit("speech_created", speech_id=event.speech_handle.id)

        @session.on("agent_state_changed")
        def on_agent_state(event):
            self.agent_state = event.new_state
            if event.new_state == "speaking":
                self.emit("agent_playout_started")
            elif event.old_state == "speaking":
                self.emit("agent_playback_stopped")
                self.emit("agent_speech_completed")
                if self.turn_id:
                    self.emit("turn_completed")
                    self.emit_trace()

        @session.on("metrics_collected")
        def on_metrics(event):
            metrics = event.metrics
            if metrics.type == "tts_metrics":
                self.emit(
                    "tts_metrics",
                    provider_ttfb_ms=round(metrics.ttfb * 1000, 1),
                    cancelled=metrics.cancelled,
                )

        @session.on("error")
        def on_error(event):
            self.emit("error", error_stage=event.source.__class__.__name__)

        @session.on("close")
        def on_close(event):
            self.emit("session_closed", close_reason=str(event.reason))

    async def aclose(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def emit_trace(self) -> dict:
        trace_key = (self.turn_id, self.response_id)
        if trace_key in self._traced_turns:
            return {}
        self._traced_turns.add(trace_key)
        durations = {**self._trace_durations(), **self.recorded_durations}
        base = self.marks.get("speech_started")
        timestamps = {
            key: round((value - base) * 1000, 1)
            for key, value in self.marks.items()
            if base is not None and value >= base
        }
        config = self.configuration
        turn_kind = (
            "cancelled_speculation"
            if self.preemptive_response_cancelled and not self.preemptive_response_reused
            else self.turn_kind
        )
        payload = {
            **self.identifiers,
            "type": "voice_latency_trace",
            "event": "voice_latency_trace",
            "turn_id": self.turn_id,
            "response_id": self.response_id,
            "speech_id": self.speech_id,
            "timestamps_ms_from_speech_start": timestamps,
            "durations_ms": durations,
            "turn_kind": turn_kind,
            "configuration": config.sanitized() if config else None,
            "flags": {
                "preemptive_generation_enabled": self.preemptive_generation_enabled,
                "preemptive_tts_enabled": False,
                "preemptive_generation_used": self.preemptive_generation_used,
                "preemptive_response_reused": self.preemptive_response_reused,
                "preemptive_response_cancelled": self.preemptive_response_cancelled,
                "tool_waited_for_commit": self.tool_waited_for_commit,
                "llm_streaming_enabled": True,
                "tool_call_used": self.turn_kind == "tool_call",
                "interrupted": self.interrupted,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("%s", json.dumps(payload, separators=(",", ":"), default=str))
        if self.publisher:
            task = asyncio.create_task(self.publisher(payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return payload

    def _trace_durations(self) -> dict[str, float]:
        pairs = {
            "stt_finalization_delay_ms": ("speech_ended", "final_transcript"),
            "turn_commit_delay_ms": ("speech_ended", "turn_committed"),
            "preemptive_head_start_ms": ("preemptive_llm_started", "turn_committed"),
            "first_chunk_before_commit_ms": (
                "preemptive_llm_first_chunk", "turn_committed"
            ),
            "llm_ttft_ms": ("llm_request_started", "llm_first_chunk"),
            "llm_total_ms": ("llm_request_started", "llm_completed"),
            "tts_start_delay_from_first_llm_chunk_ms": ("llm_first_chunk", "tts_request_started"),
            "tts_ttfb_ms": ("tts_request_started", "tts_first_audio"),
            "tool_execution_ms": ("tool_call_started", "tool_call_completed"),
        }
        return {
            name: round((self.marks[end] - self.marks[start]) * 1000, 1)
            for name, (start, end) in pairs.items()
            if start in self.marks and end in self.marks and self.marks[end] >= self.marks[start]
        }

    def _durations(self, event: str, now: float) -> dict[str, float]:
        pairs = {
            "final_transcript": ("speech_ended", "speech_end_to_final_transcript_ms"),
            "llm_request_started": ("speech_ended", "speech_end_to_llm_request_ms"),
            "llm_first_chunk": ("speech_ended", "speech_end_to_first_llm_chunk_ms"),
            "tts_first_audio": ("speech_ended", "speech_end_to_first_tts_audio_ms"),
            "agent_playout_started": (
                "speech_ended",
                "speech_end_to_agent_playback_ms",
            ),
            "agent_playback_stopped": (
                "interruption_detected",
                "interruption_to_playback_stop_ms",
            ),
            "turn_completed": ("speech_ended", "total_turn_ms"),
        }
        if event in {"llm_request_started", "llm_first_chunk", "tts_first_audio"}:
            old_start = self.marks.get("user_speech_ended")
            if old_start is not None:
                names = {
                    "llm_request_started": "speech_end_to_llm_request_ms",
                    "llm_first_chunk": "speech_end_to_first_llm_chunk_ms",
                    "tts_first_audio": "speech_end_to_first_tts_audio_ms",
                }
                return {names[event]: round((now - old_start) * 1000, 1)}
        start_and_name = pairs.get(event)
        if not start_and_name or start_and_name[0] not in self.marks:
            return {}
        return {start_and_name[1]: round((now - self.marks[start_and_name[0]]) * 1000, 1)}
