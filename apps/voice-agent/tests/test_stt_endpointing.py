from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterable

import pytest
from livekit import agents
from livekit.agents import stt, utils
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)
from livekit.plugins.elevenlabs import stt as elevenlabs_stt
from voice_agent.stt_endpointing import LocalVadCommitController, LocalVadCommitSTT


class Metrics:
    def __init__(self) -> None:
        self.requests = 0
        self.failures = 0
        self.duplicates = 0

    def record_local_vad_commit_requested(self, _: float) -> None:
        self.requests += 1

    def record_local_vad_commit_failure(self, count: int = 1) -> None:
        self.failures += count

    def record_local_vad_commit_duplicate(self) -> None:
        self.duplicates += 1


class FakeProviderStream(stt.RecognizeStream):
    def __init__(
        self,
        owner: stt.STT,
        transcripts: list[str],
        *,
        fail: bool,
    ) -> None:
        self.transcripts = transcripts
        self.fail = fail
        self.flushes = 0
        super().__init__(stt=owner, conn_options=DEFAULT_API_CONNECT_OPTIONS)

    async def _run(self) -> None:
        async for item in self._input_ch:
            if isinstance(item, self._FlushSentinel):
                self.flushes += 1
                if self.fail:
                    raise RuntimeError("commit failed")
                text = self.transcripts.pop(0)
                self._event_ch.send_nowait(
                    stt.SpeechEvent(
                        type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                        alternatives=[stt.SpeechData(language="sk", text=text)],
                    )
                )


class FakeProvider(stt.STT):
    def __init__(self, transcripts: list[str], *, fail_first: bool = False) -> None:
        super().__init__(
            capabilities=stt.STTCapabilities(streaming=True, interim_results=True)
        )
        self.transcripts = transcripts
        self.fail_first = fail_first
        self.streams: list[FakeProviderStream] = []

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
        stream = FakeProviderStream(
            self,
            self.transcripts,
            fail=self.fail_first and not self.streams,
        )
        self.streams.append(stream)
        return stream


async def open_stream(
    transcripts: list[str], *, fail_first: bool = False
) -> tuple[
    LocalVadCommitSTT,
    LocalVadCommitController,
    FakeProvider,
    stt.RecognizeStream,
    Metrics,
]:
    metrics = Metrics()
    controller = LocalVadCommitController(metrics)  # type: ignore[arg-type]
    provider = FakeProvider(transcripts, fail_first=fail_first)
    adapter = LocalVadCommitSTT(provider, controller)
    stream = adapter.stream(conn_options=APIConnectOptions(max_retry=0))
    await asyncio.sleep(0)
    return adapter, controller, provider, stream, metrics


async def next_segment(stream: AsyncIterable[stt.SpeechEvent]) -> list[stt.SpeechEvent]:
    iterator = aiter(stream)
    return [await anext(iterator), await anext(iterator)]


def test_livekit_171_elevenlabs_flush_has_native_manual_commit() -> None:
    assert '"commit": True' in inspect.getsource(elevenlabs_stt.SpeechStream._run)
    assert (
        'commit_strategy = "vad" if self._server_vad is not None else "manual"'
        in inspect.getsource(elevenlabs_stt.SpeechStream._connect_ws)
    )


@pytest.mark.asyncio
async def test_one_vad_end_commits_once_and_emits_final_then_eos() -> None:
    adapter, controller, provider, stream, metrics = await open_stream(["first"])
    session = agents.AgentSession()
    controller.attach(session)
    try:
        session.emit(
            "user_state_changed",
            agents.UserStateChangedEvent(old_state="listening", new_state="speaking"),
        )
        session.emit(
            "user_state_changed",
            agents.UserStateChangedEvent(old_state="speaking", new_state="listening"),
        )

        events = await next_segment(stream)
        assert [event.type for event in events] == [
            stt.SpeechEventType.FINAL_TRANSCRIPT,
            stt.SpeechEventType.END_OF_SPEECH,
        ]
        assert events[0].alternatives[0].text == "first"
        assert provider.streams[0].flushes == 1
        assert metrics.requests == 1
    finally:
        await stream.aclose()
        await adapter.aclose()


@pytest.mark.asyncio
async def test_duplicate_and_empty_vad_end_do_not_commit() -> None:
    adapter, controller, provider, stream, metrics = await open_stream(["first"])
    try:
        controller.speech_ended()
        controller.speech_started()
        controller.speech_ended()
        controller.speech_ended()
        await next_segment(stream)

        assert provider.streams[0].flushes == 1
        assert metrics.duplicates == 1
    finally:
        await stream.aclose()
        await adapter.aclose()


@pytest.mark.asyncio
async def test_persistent_stream_commits_two_sequential_turns() -> None:
    adapter, controller, provider, stream, _ = await open_stream(["first", "second"])
    try:
        controller.speech_started()
        controller.speech_ended()
        first = await next_segment(stream)
        controller.speech_started()
        controller.speech_ended()
        second = await next_segment(stream)

        assert first[0].alternatives[0].text == "first"
        assert second[0].alternatives[0].text == "second"
        assert provider.streams[0].flushes == 2
    finally:
        await stream.aclose()
        await adapter.aclose()


@pytest.mark.asyncio
async def test_failed_commit_uses_stream_error_path_and_replacement_resets_state() -> (
    None
):
    adapter, controller, provider, stream, metrics = await open_stream(
        ["recovered"], fail_first=True
    )
    controller.speech_started()
    controller.speech_ended()
    with pytest.raises(RuntimeError, match="commit failed"):
        await anext(stream)
    await stream.aclose()

    replacement = adapter.stream(conn_options=APIConnectOptions(max_retry=0))
    await asyncio.sleep(0)
    try:
        controller.speech_started()
        controller.speech_ended()
        events = await next_segment(replacement)
        assert events[0].alternatives[0].text == "recovered"
        assert len(provider.streams) == 2
        assert metrics.failures == 1
    finally:
        await replacement.aclose()
        await adapter.aclose()


@pytest.mark.asyncio
async def test_stream_shutdown_cleans_up_without_commit() -> None:
    adapter, controller, provider, stream, metrics = await open_stream(["unused"])
    controller.speech_started()
    await stream.aclose()
    await adapter.aclose()

    assert provider.streams[0].flushes == 0
    assert metrics.requests == 0
    assert metrics.failures == 0
