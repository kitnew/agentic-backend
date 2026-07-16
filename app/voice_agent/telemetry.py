import asyncio
import json
import logging
import time
from datetime import datetime, timezone


logger = logging.getLogger("voice_agent.telemetry")


class VoiceTelemetry:
    def __init__(self, identifiers: dict[str, str], publisher=None):
        self.identifiers = identifiers
        self.publisher = publisher
        self.marks: dict[str, float] = {}
        self.turn_id: str | None = None
        self.response_id: str | None = None
        self.agent_state = "initializing"
        self._tasks: set[asyncio.Task] = set()

    def begin_turn(self, turn_id: str, response_id: str) -> None:
        self.turn_id, self.response_id = turn_id, response_id

    def emit(self, event: str, **fields) -> dict:
        now = time.monotonic()
        self.marks[event] = now
        payload = {
            **self.identifiers,
            "turn_id": self.turn_id,
            "response_id": self.response_id,
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
        return payload

    def bind_session(self, session, on_user_speech_started=None) -> None:
        @session.on("user_state_changed")
        def on_user_state(event):
            if event.new_state == "speaking":
                if on_user_speech_started:
                    on_user_speech_started()
                self.emit("user_speech_started")
                if self.agent_state == "speaking":
                    self.emit("interruption_detected")
            elif event.old_state == "speaking":
                self.emit("user_speech_ended")

        @session.on("user_input_transcribed")
        def on_transcript(event):
            self.emit("final_transcript" if event.is_final else "interim_transcript")

        @session.on("speech_created")
        def on_speech(event):
            if event.source == "generate_reply":
                self.emit("tts_started", speech_id=event.speech_handle.id)

        @session.on("agent_state_changed")
        def on_agent_state(event):
            self.agent_state = event.new_state
            if event.new_state == "speaking":
                self.emit("agent_playback_started")
            elif event.old_state == "speaking":
                self.emit("agent_playback_stopped")
                if self.turn_id:
                    self.emit("turn_completed")

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

    def _durations(self, event: str, now: float) -> dict[str, float]:
        pairs = {
            "final_transcript": ("user_speech_ended", "speech_end_to_final_transcript_ms"),
            "graph_started": ("user_speech_ended", "speech_end_to_graph_start_ms"),
            "llm_first_token": ("user_speech_ended", "speech_end_to_first_llm_token_ms"),
            "tts_first_audio": ("user_speech_ended", "speech_end_to_first_tts_audio_ms"),
            "agent_playback_started": (
                "user_speech_ended",
                "speech_end_to_agent_playback_ms",
            ),
            "agent_playback_stopped": (
                "interruption_detected",
                "interruption_to_playback_stop_ms",
            ),
            "turn_completed": ("user_speech_ended", "total_turn_ms"),
        }
        start_and_name = pairs.get(event)
        if not start_and_name or start_and_name[0] not in self.marks:
            return {}
        return {start_and_name[1]: round((now - self.marks[start_and_name[0]]) * 1000, 1)}
