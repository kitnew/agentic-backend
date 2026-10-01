import asyncio
import math
from array import array
from types import SimpleNamespace
from uuid import uuid4

import pytest
from voice_agent import ringback


def test_tone_frame_has_425_hz_mono_24khz_and_faded_edges() -> None:
    frames = [ringback.tone_frame(24000, offset) for offset in range(0, 24000, 480)]
    samples = array("h")
    for frame in frames:
        assert (frame.sample_rate, frame.num_channels, frame.samples_per_channel) == (
            24000,
            1,
            480,
        )
        samples.frombytes(bytes(frame.data))
    assert len(samples) == 24000
    assert samples[0] == samples[-1] == 0
    assert max(abs(value) for value in samples) <= 6000
    # A 425 Hz sine has 425 positive zero crossings in one second.
    assert sum(samples[i - 1] <= 0 < samples[i] for i in range(1, len(samples))) == 425
    assert math.isclose(ringback.SILENCE_SECONDS, 4.0)


@pytest.mark.asyncio
async def test_player_stops_in_silence_and_stale_attempt_cannot_stop_next(
    monkeypatch,
) -> None:
    sources = []
    silence = asyncio.Event()
    published = []
    unpublished = []

    class Source:
        def __init__(self, sample_rate, channels, queue_size_ms):
            assert (sample_rate, channels, queue_size_ms) == (24000, 1, 20)
            self.frames = []
            self.cleared = 0
            sources.append(self)

        async def capture_frame(self, frame):
            self.frames.append(frame)

        def clear_queue(self):
            self.cleared += 1

        async def aclose(self):
            return None

    class Participant:
        async def publish_track(self, track, options):
            sid = f"track-{len(published)}"
            published.append(sid)
            return SimpleNamespace(sid=sid)

        async def unpublish_track(self, sid):
            unpublished.append(sid)

    async def fake_sleep(delay):
        assert delay == 4.0
        silence.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(ringback.rtc, "AudioSource", Source)
    monkeypatch.setattr(
        ringback.rtc.LocalAudioTrack,
        "create_audio_track",
        lambda name, source: (name, source),
    )
    monkeypatch.setattr(ringback.asyncio, "sleep", fake_sleep)
    player = ringback.RingbackPlayer(
        uuid4(), SimpleNamespace(local_participant=Participant()), "caller"
    )
    attempt_a, attempt_b = uuid4(), uuid4()
    player.start(attempt_a)
    await silence.wait()
    assert len(sources[0].frames) == 50
    assert len(published) == 1
    player.stop("answered", attempt_a)
    assert sources[0].cleared
    silence.clear()
    player.start(attempt_b)
    await silence.wait()
    player.stop("stale", attempt_a)
    assert not sources[1].cleared
    assert len(sources[1].frames) == 50
    player.stop("timed_out", attempt_b)
    await player.aclose()
    assert set(unpublished) == set(published)


@pytest.mark.asyncio
async def test_stop_during_tone_on_prevents_another_frame(monkeypatch) -> None:
    capturing = asyncio.Event()
    source_holder = []

    class Source:
        def __init__(self, *args, **kwargs):
            self.frames = []
            self.cleared = False
            source_holder.append(self)

        async def capture_frame(self, frame):
            self.frames.append(frame)
            capturing.set()
            await asyncio.Event().wait()

        def clear_queue(self):
            self.cleared = True

        async def aclose(self):
            return None

    class Participant:
        async def publish_track(self, track, options):
            return SimpleNamespace(sid="ringback")

        async def unpublish_track(self, sid):
            assert sid == "ringback"

    monkeypatch.setattr(ringback.rtc, "AudioSource", Source)
    monkeypatch.setattr(
        ringback.rtc.LocalAudioTrack,
        "create_audio_track",
        lambda name, source: (name, source),
    )
    player = ringback.RingbackPlayer(
        uuid4(), SimpleNamespace(local_participant=Participant()), "caller"
    )
    player.start(uuid4())
    await capturing.wait()
    player.stop("answered")
    await player.aclose()
    assert source_holder[0].cleared
    assert len(source_holder[0].frames) == 1
