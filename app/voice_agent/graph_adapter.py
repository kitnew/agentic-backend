import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

from livekit.agents import llm

from app.agent_runtime.voice_processing_executor import VoiceProcessingExecutor
from app.agent_runtime.voice_turn_processor import VoiceTurnProcessor
from app.voice.schemas import FinalizedTranscriptRequest


_DONE = object()


@dataclass
class _Turn:
    turn_id: str
    response_id: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    active: bool = True
    emitted: bool = False
    error: Exception | None = None


class GraphStreamAdapter(llm.LLM):
    def __init__(self, metadata, telemetry, processor=None, stt_model="scribe_v2_realtime"):
        super().__init__()
        self.metadata = metadata
        self.telemetry = telemetry
        self.stt_model = stt_model
        self.executor = VoiceProcessingExecutor(
            max_workers=1,
            poll_interval_seconds=0.001,
            turn_processor=processor or VoiceTurnProcessor(),
        )
        self._lock = asyncio.Lock()
        self._seen: set[str] = set()
        self._turns: set[asyncio.Task] = set()
        self._states: list[_Turn] = []
        self._closed = False

    def chat(self, **kwargs):
        raise RuntimeError("GraphStreamAdapter must be consumed through HospitalityAgent.llm_node")

    async def stream_turn(self, transcript: str, turn_id: str):
        if self._closed or turn_id in self._seen:
            return
        self._seen.add(turn_id)
        state = _Turn(turn_id=turn_id, response_id=str(uuid4()))
        self._states.append(state)
        self.telemetry.begin_turn(state.turn_id, state.response_id)
        task = asyncio.create_task(self._run(state, transcript))
        self._turns.add(task)
        task.add_done_callback(self._turns.discard)
        try:
            while True:
                item = await state.queue.get()
                if item is _DONE:
                    if state.error:
                        raise state.error
                    return
                yield item
        finally:
            state.active = False

    async def _run(self, state: _Turn, transcript: str) -> None:
        try:
            async with self._lock:
                self.telemetry.begin_turn(state.turn_id, state.response_id)
                self.telemetry.emit("graph_started")
                loop = asyncio.get_running_loop()

                def on_text(text: str) -> None:
                    loop.call_soon_threadsafe(self._push, state, text)

                result = await self.executor.process_transcript(
                    FinalizedTranscriptRequest(
                        tenant_id=self.metadata.tenant_id,
                        transcript=transcript,
                        provider="elevenlabs",
                        model=self.stt_model,
                        language=self.metadata.language,
                        conversation_id=str(self.metadata.conversation_id),
                        channel="voice",
                        metadata={
                            "call_session_id": str(self.metadata.call_session_id),
                            "channel": "voice",
                            "language": self.metadata.language,
                            "thread_id": str(self.metadata.conversation_id),
                            "idempotency_key": (
                                f"livekit:{self.metadata.call_session_id}:{state.turn_id}"
                            ),
                        },
                    ),
                    text_callback=on_text,
                    synthesize=False,
                )
                await asyncio.sleep(0)
                response = result.response
                if state.active and not state.emitted:
                    self._push(state, response.response_text or "")
                self.telemetry.emit("graph_completed")
        except Exception as exc:
            state.error = exc
            self.telemetry.emit("error", error_stage="graph")
        finally:
            state.queue.put_nowait(_DONE)

    def _push(self, state: _Turn, text: str) -> None:
        if not state.active or not text:
            return
        if not state.emitted:
            state.emitted = True
            self.telemetry.begin_turn(state.turn_id, state.response_id)
            self.telemetry.emit("llm_first_token")
        state.queue.put_nowait(text)

    async def aclose(self) -> None:
        self._closed = True
        for state in self._states:
            state.active = False
        if self._turns:
            await asyncio.gather(*self._turns, return_exceptions=True)
        self.executor.shutdown()
