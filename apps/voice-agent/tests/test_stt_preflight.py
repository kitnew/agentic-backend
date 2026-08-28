from __future__ import annotations

import pytest
from livekit.agents import stt, utils
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)
from voice_agent.stt_preflight import InterimPreflightSTT


def transcript(kind: stt.SpeechEventType, text: str = "") -> stt.SpeechEvent:
    alternatives = [stt.SpeechData(language="sk", text=text)] if text else []
    return stt.SpeechEvent(type=kind, alternatives=alternatives)


class FakeStream(stt.RecognizeStream):
    def __init__(self, owner: stt.STT, events: list[stt.SpeechEvent]) -> None:
        self._events = events
        super().__init__(stt=owner, conn_options=DEFAULT_API_CONNECT_OPTIONS)

    async def _run(self) -> None:
        async for _ in self._input_ch:
            pass
        for event in self._events:
            self._event_ch.send_nowait(event)


class FakeSTT(stt.STT):
    def __init__(self, events: list[stt.SpeechEvent]) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=True, interim_results=True)
        )
        self._speech_events = events

    async def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.SpeechEvent:
        raise NotImplementedError

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.RecognizeStream:
        return FakeStream(self, self._speech_events)


async def adapt(
    events: list[stt.SpeechEvent],
    *,
    minimum: int = 20,
    growth: int = 12,
    maximum: int = 2,
) -> list[stt.SpeechEvent]:
    adapter = InterimPreflightSTT(
        FakeSTT(events),
        min_transcript_chars=minimum,
        min_growth_chars=growth,
        max_generations_per_turn=maximum,
    )
    stream = adapter.stream()
    stream.end_input()
    output = [event async for event in stream]
    await stream.aclose()
    await adapter.aclose()
    return output


@pytest.mark.asyncio
async def test_first_preflight_waits_for_minimum_transcript_length() -> None:
    output = await adapt(
        [
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 19),
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 20),
        ]
    )
    assert [event.type for event in output] == [
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
        stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
    ]


@pytest.mark.asyncio
async def test_insignificant_interim_growth_remains_interim() -> None:
    insignificant = transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 31)
    output = await adapt(
        [
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 20),
            insignificant,
        ]
    )
    assert [event.type for event in output] == [
        stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
    ]
    assert output[1] is insignificant


@pytest.mark.asyncio
async def test_significant_growth_replaces_existing_speculation() -> None:
    output = await adapt(
        [
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 20),
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 32),
        ]
    )
    assert [event.type for event in output] == [
        stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
        stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
    ]


@pytest.mark.asyncio
async def test_maximum_generations_is_enforced_per_turn() -> None:
    output = await adapt(
        [
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 20),
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 32),
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 44),
        ]
    )
    assert [event.type for event in output] == [
        stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
        stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
        stt.SpeechEventType.INTERIM_TRANSCRIPT,
    ]


@pytest.mark.asyncio
async def test_attempt_state_resets_on_final_eos_and_new_turn() -> None:
    final = transcript(stt.SpeechEventType.FINAL_TRANSCRIPT, "x" * 32)
    eos = transcript(stt.SpeechEventType.END_OF_SPEECH)
    output = await adapt(
        [
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 20),
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 32),
            final,
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "y" * 20),
            eos,
            transcript(stt.SpeechEventType.START_OF_SPEECH),
            transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "z" * 20),
        ]
    )
    assert [event.type for event in output] == [
        stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
        stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
        stt.SpeechEventType.FINAL_TRANSCRIPT,
        stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
        stt.SpeechEventType.END_OF_SPEECH,
        stt.SpeechEventType.START_OF_SPEECH,
        stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
    ]
    assert output[2] is final
    assert output[4] is eos


@pytest.mark.asyncio
async def test_new_stream_starts_with_clean_attempt_state() -> None:
    events = [transcript(stt.SpeechEventType.INTERIM_TRANSCRIPT, "x" * 20)]
    adapter = InterimPreflightSTT(
        FakeSTT(events),
        min_transcript_chars=20,
        min_growth_chars=12,
        max_generations_per_turn=1,
    )
    try:
        for _ in range(2):
            stream = adapter.stream()
            stream.end_input()
            output = [event async for event in stream]
            await stream.aclose()
            assert output[0].type == stt.SpeechEventType.PREFLIGHT_TRANSCRIPT
    finally:
        await adapter.aclose()
