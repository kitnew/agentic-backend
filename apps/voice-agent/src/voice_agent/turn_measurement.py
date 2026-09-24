"""Opt-in, process-local voice turn timing. No conversational content is recorded."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from opentelemetry import trace

logger = logging.getLogger(__name__)

PAIRS = {
    "speech_to_eou": ("speech_end_proxy", "eou"),
    "eou_to_stt_final": ("eou", "stt_final"),
    "stt_final_to_eou": ("stt_final", "eou"),
    "speech_to_stt_final": ("speech_end_proxy", "stt_final"),
    "speech_to_stt_first_partial": (
        "speech_end_proxy",
        "stt_first_partial_after_speech",
    ),
    "stt_to_llm_start": ("stt_final", "llm_start"),
    "eou_to_llm_start": ("eou", "llm_start"),
    "llm_ttft": ("llm_start", "llm_first_token"),
    "llm_to_first_speakable": ("llm_start", "first_speakable"),
    "first_token_to_speakable": ("llm_first_token", "first_speakable"),
    "first_token_to_tts_input": ("llm_first_token", "tts_input_first_text"),
    "speakable_to_tts_start": ("first_speakable", "tts_start"),
    "tts_input_to_speakable": ("tts_input_first_text", "first_speakable"),
    "tts_ttfb": ("tts_start", "tts_first_audio"),
    "tts_to_playout_enqueue": ("tts_first_audio", "playout_enqueue"),
    "playout_enqueue_to_output": ("playout_enqueue", "output_boundary_proxy"),
    "speech_to_first_audio_received": ("speech_end_proxy", "tts_first_audio"),
    "speech_to_first_audio_output": ("speech_end_proxy", "output_boundary_proxy"),
    "first_audio_to_output": ("tts_first_audio", "output_boundary_proxy"),
    "speech_to_response_created": ("speech_end_proxy", "response_created"),
    "speech_to_realtime_first_audio": ("speech_end_proxy", "realtime_first_audio"),
    "realtime_response_to_first_audio": ("response_created", "realtime_first_audio"),
    "realtime_first_audio_to_output": ("realtime_first_audio", "output_boundary_proxy"),
    "realtime_eou_to_response": ("eou", "response_created"),
    "realtime_response_to_output": ("response_created", "output_boundary_proxy"),
    "realtime_response_to_speakable": ("response_created", "first_speakable"),
    "realtime_response_to_tts_input": ("response_created", "tts_input_first_text"),
}

CAUSAL_STAGES = {
    "cascade": (
        "speech_to_stt_final",
        "stt_final_to_eou",
        "eou_to_llm_start",
        "llm_ttft",
        "first_token_to_tts_input",
        "tts_input_to_speakable",
        "tts_ttfb",
        "first_audio_to_output",
    ),
    "realtime": (
        "speech_to_response_created",
        "realtime_response_to_first_audio",
        "realtime_first_audio_to_output",
    ),
    "half-cascade": (
        "speech_to_response_created",
        "realtime_response_to_tts_input",
        "tts_input_to_speakable",
        "tts_ttfb",
        "first_audio_to_output",
    ),
}


def derive(timestamps: dict[str, int | None]) -> dict[str, float | None]:
    """Only compare monotonic timestamps captured by this Voice Agent process."""
    result = {}
    for name, (start_key, end_key) in PAIRS.items():
        start, end = timestamps.get(start_key), timestamps.get(end_key)
        result[name] = (
            round((end - start) / 1_000_000, 3)
            if isinstance(start, int) and isinstance(end, int) and end >= start
            else None
        )
    return result


def causal_sum(architecture: str, latencies: dict[str, float | None]) -> float | None:
    stages = [latencies.get(name) for name in CAUSAL_STAGES[architecture]]
    if any(value is None for value in stages):
        return None
    total = latencies.get("speech_to_first_audio_output")
    sum_ms = round(sum(value for value in stages if value is not None), 3)
    return sum_ms if total is not None and abs(sum_ms - total) <= 0.01 else None


@dataclass
class _Turn:
    turn_id: str = field(default_factory=lambda: str(uuid4()))
    timestamps: dict[str, int] = field(default_factory=dict)
    speech_id: str | None = None
    span: Any = None
    emitted: bool = False
    llm_usage: dict[str, int | None] = field(default_factory=dict)


class TurnRecorder:
    """Callbacks stay passive; missing SDK boundaries remain null in records."""

    def __init__(
        self,
        directory: Path,
        *,
        call_id: str,
        architecture: str,
        tenant_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        self.directory = directory
        self.call_id = call_id
        self.architecture = architecture
        self.tenant_id = tenant_id
        self.metadata = metadata
        self.turns: list[_Turn] = []
        self.stt_stream_started_ns: int | None = None
        self.directory.mkdir(parents=True, exist_ok=True)
        manifest = {
            "call_id": call_id,
            "architecture": architecture,
            "tenant_id": tenant_id,
            "started_utc": datetime.now(UTC).isoformat(),
            "metadata": metadata,
            "clock": "time.perf_counter_ns, Voice Agent process only",
            "semantics": {
                "speech_end_proxy": "cascade: local VAD end callback minus SDK silence and inference durations; realtime: server input_speech_stopped receipt",
                "eou": "cascade: LiveKit on_end_of_turn accepted; realtime: unavailable (no commit acknowledgment exposed)",
                "input_committed": "cascade: on_user_turn_completed callback entered with committed user message; Realtime server commit acknowledgment unavailable",
                "stt_final": "standalone STT final observed by agent; observer for realtime and half-cascade",
                "first_speakable": "SDK first text sent to ElevenLabs after production tokenizer, reconstructed from frame userdata perf_counter",
                "tts_first_audio": "first decoded frame yielded by LiveKit TTS node, includes SDK decode time",
                "realtime_first_audio": "first decoded Realtime frame yielded by LiveKit realtime_audio_output_node",
                "output_boundary_proxy": "LiveKit RoomIO playback_started callback, immediately before AudioSource.capture_frame; not RTP or caller audibility",
            },
            "unavailable": [
                "physical speech end",
                "first provider TTS audio bytes",
                "playout enqueue",
                "first RTP packet sent",
                "SIP/PSTN delivery and caller audibility",
            ],
        }
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    def start(self, *, speech_started: int | None = None) -> None:
        turn = _Turn()
        turn.span = trace.get_tracer("voice-agent.turn").start_span("voice.turn")
        turn.span.set_attribute("call.id", self.call_id)
        turn.span.set_attribute("voice.turn.id", turn.turn_id)
        turn.span.set_attribute("voice.architecture", self.architecture)
        if self.tenant_id:
            turn.span.set_attribute("tenant.id", self.tenant_id)
        self.turns.append(turn)
        if speech_started is not None:
            self.mark("speech_started", speech_started, turn=turn)

    def stream_started(self) -> None:
        if self.stt_stream_started_ns is None:
            self.stt_stream_started_ns = time.perf_counter_ns()

    def _pending(self) -> _Turn | None:
        return next((turn for turn in reversed(self.turns) if not turn.emitted), None)

    def mark(
        self, name: str, at_ns: int | None = None, *, turn: _Turn | None = None
    ) -> None:
        turn = turn or self._pending()
        if turn is None or turn.emitted or name in turn.timestamps:
            return
        timestamp = at_ns if at_ns is not None else time.perf_counter_ns()
        turn.timestamps[name] = timestamp
        turn.span.add_event(name)

    def bind_speech(self, speech_id: str) -> None:
        turn = next(
            (
                item
                for item in self.turns
                if not item.emitted and item.speech_id is None
            ),
            None,
        )
        if turn is not None:
            turn.speech_id = speech_id

    def stt_partial(self) -> None:
        turn = self._pending()
        if turn is None:
            return
        self.mark("stt_first_partial", turn=turn)
        if "speech_end_proxy" in turn.timestamps:
            self.mark("stt_first_partial_after_speech", turn=turn)

    def mark_speech(
        self, speech_id: str | None, name: str, at_ns: int | None = None
    ) -> None:
        if speech_id is None:
            return
        turn = next(
            (
                item
                for item in self.turns
                if item.speech_id == speech_id and not item.emitted
            ),
            None,
        )
        if turn is not None:
            self.mark(name, at_ns, turn=turn)

    def output_started(self) -> None:
        turn = next(
            (
                item
                for item in self.turns
                if item.speech_id
                and not item.emitted
                and "output_boundary_proxy" not in item.timestamps
            ),
            None,
        )
        if turn is None:
            return
        self.mark("output_boundary_proxy", turn=turn)

    def complete_speech(self, speech_id: str, *, interrupted: bool = False) -> None:
        turn = next(
            (
                item
                for item in self.turns
                if item.speech_id == speech_id and not item.emitted
            ),
            None,
        )
        if turn is not None:
            if "output_boundary_proxy" in turn.timestamps:
                self.emit(turn)
            else:
                turn.speech_id = None
                if interrupted:
                    for name in (
                        "llm_start",
                        "llm_first_token",
                        "tts_input_first_text",
                        "first_speakable",
                        "tts_start",
                        "tts_first_audio",
                        "realtime_first_audio",
                        "response_created",
                    ):
                        turn.timestamps.pop(name, None)

    def record_llm_usage(self, metric: object) -> None:
        speech_id = getattr(metric, "speech_id", None)
        turn = next(
            (
                item
                for item in self.turns
                if item.speech_id == speech_id and not item.emitted
            ),
            None,
        )
        if turn is None or getattr(metric, "type", None) != "llm_metrics":
            return
        turn.llm_usage = {
            "input_tokens": getattr(metric, "prompt_tokens", None),
            "cached_input_tokens": getattr(metric, "prompt_cached_tokens", None),
            "output_tokens": getattr(metric, "completion_tokens", None),
        }

    def flush(self) -> None:
        for turn in self.turns:
            if not turn.emitted:
                self.emit(turn)

    def emit(self, turn: _Turn) -> None:
        if turn.emitted:
            return
        turn.emitted = True
        context = turn.span.get_span_context()
        timestamps = {
            name: turn.timestamps.get(name)
            for name in (
                "speech_started",
                "speech_end_proxy",
                "vad_end_received",
                "eou",
                "input_committed",
                "stt_first_partial",
                "stt_first_partial_after_speech",
                "stt_final",
                "llm_start",
                "llm_first_token",
                "first_speakable",
                "tts_input_first_text",
                "response_created",
                "tts_start",
                "tts_first_audio",
                "realtime_first_audio",
                "playout_enqueue",
                "output_boundary_proxy",
            )
        }
        latencies = derive(timestamps)
        record = {
            "call_id": self.call_id,
            "turn_id": turn.turn_id,
            "trace_id": f"{context.trace_id:032x}" if context.is_valid else None,
            "architecture": self.architecture,
            "tenant_id": self.tenant_id,
            "metadata": self.metadata,
            "stt_stream_started_ns": self.stt_stream_started_ns,
            "llm_usage": turn.llm_usage or None,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "timestamps_ns": timestamps,
            "latencies_ms": latencies,
            "causal_stage_sum_ms": causal_sum(self.architecture, latencies),
            "metric_classes": {
                name: (
                    "observer"
                    if self.architecture != "cascade" and "stt" in name
                    else "context"
                    if (self.architecture == "cascade" and name.startswith("realtime_"))
                    or (self.architecture != "cascade" and name.startswith("llm_"))
                    else "causal"
                )
                for name in PAIRS
            },
            "classification": {
                "stt_final": "causal" if self.architecture == "cascade" else "observer",
                "response_created": "causal"
                if self.architecture != "cascade"
                else "context",
                "output_boundary_proxy": "causal",
            },
        }
        try:
            with (self.directory / "turns.jsonl").open("a") as file:
                file.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError:
            logger.exception("Voice turn benchmark record write failed")
        finally:
            turn.span.end()
