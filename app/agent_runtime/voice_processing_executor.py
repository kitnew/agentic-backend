import asyncio
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from app.agent_runtime.voice_turn_processor import VoiceTurnProcessor
from app.voice.schemas import VoiceMessageRequest, VoiceMessageResponse


class VoiceProcessingTimeoutError(Exception):
    pass


@dataclass(frozen=True)
class VoiceProcessingResult:
    response: VoiceMessageResponse
    processing_duration_ms: int


class VoiceProcessingExecutor:
    def __init__(
        self,
        *,
        max_workers: int | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float = 0.01,
        turn_processor: VoiceTurnProcessor | None = None,
    ):
        self.max_workers = max_workers or int(os.getenv("VOICE_WS_PROCESSING_MAX_WORKERS", "4"))
        self.timeout_seconds = timeout_seconds or float(
            os.getenv("VOICE_WS_PROCESSING_TIMEOUT_SECONDS", "120")
        )
        self.poll_interval_seconds = poll_interval_seconds
        self.turn_processor = turn_processor or VoiceTurnProcessor()
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="voice-ws",
        )
        self._closed = False

    async def process(self, request: VoiceMessageRequest) -> VoiceProcessingResult:
        return await self._process(request, self.turn_processor.process)

    async def process_transcript(self, request) -> VoiceProcessingResult:
        return await self._process(request, self.turn_processor.process_transcript)

    async def _process(self, request, processor) -> VoiceProcessingResult:
        if self._closed:
            raise RuntimeError("Voice processing executor is closed")

        started_at = time.perf_counter()
        future = self._executor.submit(processor, request)
        try:
            response = await self._await_future(future)
        except asyncio.CancelledError:
            future.cancel()
            raise

        return VoiceProcessingResult(
            response=response,
            processing_duration_ms=int((time.perf_counter() - started_at) * 1000),
        )

    async def _await_future(self, future: Future[Any]) -> VoiceMessageResponse:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            if future.done():
                return future.result()
            if time.monotonic() >= deadline:
                future.cancel()
                raise VoiceProcessingTimeoutError(
                    f"Voice processing timed out after {self.timeout_seconds:g} seconds"
                )
            await asyncio.sleep(self.poll_interval_seconds)

    def shutdown(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
