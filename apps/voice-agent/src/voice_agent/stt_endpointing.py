from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterable
from typing import TYPE_CHECKING, Any

from livekit import agents, rtc
from livekit.agents import stt, utils
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)

if TYPE_CHECKING:
    from voice_agent.observability import VoiceMetrics


class LocalVadCommitController:
    """Commit the active persistent STT stream once per local-VAD segment."""

    def __init__(self, metrics: VoiceMetrics | None = None) -> None:
        self._metrics = metrics
        self._session: agents.AgentSession | None = None
        self._stream: stt.RecognizeStream | None = None
        self._speech_active = False
        self._segment_committed = False
        self._pending_commits = 0

    def attach(self, session: agents.AgentSession) -> None:
        self._session = session
        session.on("user_state_changed", self._on_user_state_changed)
        session.on("close", self._on_close)

    def detach(self) -> None:
        if self._session is not None:
            self._session.off("user_state_changed", self._on_user_state_changed)
            self._session.off("close", self._on_close)
        self._session = None
        self._stream = None
        self._speech_active = False
        self._segment_committed = False
        self._pending_commits = 0

    def replace_stream(self, stream: stt.RecognizeStream) -> None:
        if self._stream is not None and self._stream is not stream:
            self.stream_failed(self._stream)
            self._speech_active = False
            self._segment_committed = False
        self._stream = stream

    def clear_stream(self, stream: stt.RecognizeStream) -> None:
        if self._stream is stream:
            self._stream = None

    def stream_failed(self, stream: stt.RecognizeStream) -> None:
        if self._stream is not stream:
            return
        if self._pending_commits and self._metrics is not None:
            self._metrics.record_local_vad_commit_failure(self._pending_commits)
        self._pending_commits = 0
        self._speech_active = False
        self._segment_committed = False

    def speech_started(self) -> None:
        self._speech_active = True
        self._segment_committed = False

    def speech_ended(self) -> None:
        if not self._speech_active:
            if self._segment_committed and self._metrics is not None:
                self._metrics.record_local_vad_commit_duplicate()
            return
        if self._segment_committed:
            if self._metrics is not None:
                self._metrics.record_local_vad_commit_duplicate()
            return

        self._speech_active = False
        self._segment_committed = True
        stream = self._stream
        if stream is None:
            if self._metrics is not None:
                self._metrics.record_local_vad_commit_failure()
            return

        requested_at = time.perf_counter()
        self._pending_commits += 1
        if self._metrics is not None:
            self._metrics.record_local_vad_commit_requested(requested_at)
        try:
            stream.flush()
        except Exception:
            self._pending_commits -= 1
            if self._metrics is not None:
                self._metrics.record_local_vad_commit_failure()
            raise

    def final_received(self, stream: stt.RecognizeStream) -> bool:
        if self._stream is not stream or self._pending_commits == 0:
            return False
        self._pending_commits -= 1
        return True

    def provider_eos_received(self, stream: stt.RecognizeStream) -> bool:
        if self._stream is not stream or self._pending_commits == 0:
            return False
        self._pending_commits -= 1
        return True

    def _on_user_state_changed(self, event: agents.UserStateChangedEvent) -> None:
        if event.new_state == "speaking":
            self.speech_started()
        elif event.old_state == "speaking" and event.new_state == "listening":
            self.speech_ended()

    def _on_close(self, _: object) -> None:
        self.detach()


class LocalVadCommitSTT(stt.STT):
    """Expose provider streams to local VAD and add EOS after Scribe FINAL."""

    def __init__(
        self,
        wrapped: stt.STT,
        controller: LocalVadCommitController,
    ) -> None:
        super().__init__(capabilities=wrapped.capabilities)
        self._wrapped = wrapped
        self.controller = controller
        wrapped.on("metrics_collected", self._forward_metrics)
        wrapped.on("error", self._forward_error)

    @property
    def model(self) -> str:
        return self._wrapped.model

    @property
    def provider(self) -> str:
        return self._wrapped.provider

    @property
    def wrapped_stt(self) -> stt.STT:
        return self._wrapped

    async def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.SpeechEvent:
        return await self._wrapped.recognize(
            buffer, language=language, conn_options=conn_options
        )

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        return _LocalVadCommitStream(
            stt=self,
            wrapped=self._wrapped.stream(language=language, conn_options=conn_options),
            controller=self.controller,
            conn_options=conn_options,
        )

    def _update_session_keyterms(self, keyterms: list[str]) -> None:
        self._wrapped._update_session_keyterms(keyterms)

    def _push_conversation_item(self, item: Any) -> None:
        self._wrapped._push_conversation_item(item)

    def _forward_metrics(self, metric: object) -> None:
        self.emit("metrics_collected", metric)

    def _forward_error(self, error: object) -> None:
        self.emit("error", error)

    async def aclose(self) -> None:
        self.controller.detach()
        self._wrapped.off("metrics_collected", self._forward_metrics)
        self._wrapped.off("error", self._forward_error)
        await self._wrapped.aclose()


class _LocalVadCommitStream(stt.RecognizeStream):
    def __init__(
        self,
        *,
        stt: stt.STT,
        wrapped: stt.RecognizeStream,
        controller: LocalVadCommitController,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(stt=stt, conn_options=conn_options)
        self._wrapped = wrapped
        self._controller = controller

    async def _metrics_monitor_task(
        self, event_aiter: AsyncIterable[stt.SpeechEvent]
    ) -> None:
        async for _ in event_aiter:
            pass

    async def _run(self) -> None:
        self._controller.replace_stream(self)

        async def forward_input() -> None:
            async for item in self._input_ch:
                if isinstance(item, rtc.AudioFrame):
                    self._wrapped.push_frame(item)
                else:
                    self._wrapped.flush()
            with contextlib.suppress(RuntimeError):
                self._wrapped.end_input()

        async def forward_output() -> None:
            async for event in self._wrapped:
                if event.type == stt.SpeechEventType.END_OF_SPEECH:
                    if self._controller.provider_eos_received(self):
                        self._event_ch.send_nowait(event)
                    continue

                self._event_ch.send_nowait(event)
                if (
                    event.type == stt.SpeechEventType.FINAL_TRANSCRIPT
                    and self._controller.final_received(self)
                ):
                    self._event_ch.send_nowait(
                        stt.SpeechEvent(type=stt.SpeechEventType.END_OF_SPEECH)
                    )

        tasks = [
            asyncio.create_task(forward_input()),
            asyncio.create_task(forward_output()),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._controller.stream_failed(self)
            raise
        finally:
            self._controller.clear_stream(self)
            await utils.aio.cancel_and_wait(*tasks)
            await self._wrapped.aclose()
