from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterable
from dataclasses import replace
from typing import Any

from livekit import rtc
from livekit.agents import stt, utils
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)


class InterimPreflightSTT(stt.STT):
    """Promote changing Scribe interim text into LiveKit preflight events."""

    def __init__(
        self,
        wrapped: stt.STT,
        *,
        min_transcript_chars: int,
        min_growth_chars: int,
        max_generations_per_turn: int,
    ) -> None:
        super().__init__(capabilities=wrapped.capabilities)
        self._wrapped = wrapped
        self._min_transcript_chars = min_transcript_chars
        self._min_growth_chars = min_growth_chars
        self._max_generations_per_turn = max_generations_per_turn
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
        return _InterimPreflightStream(
            stt=self,
            wrapped=self._wrapped.stream(language=language, conn_options=conn_options),
            conn_options=conn_options,
            min_transcript_chars=self._min_transcript_chars,
            min_growth_chars=self._min_growth_chars,
            max_generations_per_turn=self._max_generations_per_turn,
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
        self._wrapped.off("metrics_collected", self._forward_metrics)
        self._wrapped.off("error", self._forward_error)
        await self._wrapped.aclose()


class _InterimPreflightStream(stt.RecognizeStream):
    def __init__(
        self,
        *,
        stt: stt.STT,
        wrapped: stt.RecognizeStream,
        conn_options: APIConnectOptions,
        min_transcript_chars: int,
        min_growth_chars: int,
        max_generations_per_turn: int,
    ) -> None:
        super().__init__(stt=stt, conn_options=conn_options)
        self._wrapped = wrapped
        self._min_transcript_chars = min_transcript_chars
        self._min_growth_chars = min_growth_chars
        self._max_generations_per_turn = max_generations_per_turn

    async def _metrics_monitor_task(
        self, event_aiter: AsyncIterable[stt.SpeechEvent]
    ) -> None:
        async for _ in event_aiter:
            pass  # the wrapped provider remains the metrics authority

    async def _run(self) -> None:
        async def forward_input() -> None:
            async for item in self._input_ch:
                if isinstance(item, rtc.AudioFrame):
                    self._wrapped.push_frame(item)
                else:
                    self._wrapped.flush()
            with contextlib.suppress(RuntimeError):
                self._wrapped.end_input()

        async def forward_output() -> None:
            preflight_text: str | None = None
            generation_count = 0

            def reset() -> None:
                nonlocal preflight_text, generation_count
                preflight_text = None
                generation_count = 0

            async for event in self._wrapped:
                if event.type == stt.SpeechEventType.START_OF_SPEECH:
                    reset()
                elif (
                    event.type == stt.SpeechEventType.INTERIM_TRANSCRIPT
                    and event.alternatives
                ):
                    text = event.alternatives[0].text.strip()
                    required_chars = (
                        self._min_transcript_chars
                        if preflight_text is None
                        else len(preflight_text) + self._min_growth_chars
                    )
                    should_preflight = (
                        bool(text)
                        and len(text) >= required_chars
                        and generation_count < self._max_generations_per_turn
                    )
                    if should_preflight:
                        preflight_text = text
                        generation_count += 1
                        event = replace(
                            event, type=stt.SpeechEventType.PREFLIGHT_TRANSCRIPT
                        )
                elif event.type in (
                    stt.SpeechEventType.FINAL_TRANSCRIPT,
                    stt.SpeechEventType.END_OF_SPEECH,
                ):
                    reset()
                self._event_ch.send_nowait(event)

        tasks = [
            asyncio.create_task(forward_input()),
            asyncio.create_task(forward_output()),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            await utils.aio.cancel_and_wait(*tasks)
            await self._wrapped.aclose()
