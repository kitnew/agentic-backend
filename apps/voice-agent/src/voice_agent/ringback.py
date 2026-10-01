import asyncio
import logging
import math
from array import array
from uuid import UUID

from livekit import rtc

logger = logging.getLogger(__name__)

FREQUENCY = 425
TONE_SECONDS = 1.0
SILENCE_SECONDS = 4.0
FRAME_SECONDS = 0.02
FADE_SECONDS = 0.01


def tone_frame(sample_rate: int, offset: int) -> rtc.AudioFrame:
    count = int(sample_rate * FRAME_SECONDS)
    total = int(sample_rate * TONE_SECONDS)
    fade = int(sample_rate * FADE_SECONDS)
    samples = array(
        "h",
        (
            round(
                6000
                * math.sin(2 * math.pi * FREQUENCY * i / sample_rate)
                * min(1.0, i / fade, (total - 1 - i) / fade)
            )
            for i in range(offset, offset + count)
        ),
    )
    return rtc.AudioFrame(
        data=samples.tobytes(),
        sample_rate=sample_rate,
        num_channels=1,
        samples_per_channel=count,
    )


class RingbackPlayer:
    def __init__(self, call_id: UUID, room: rtc.Room, caller_identity: str) -> None:
        self._call_id = call_id
        self._room = room
        self._caller_identity = caller_identity
        self._attempt_id: UUID | None = None
        self._task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._source: rtc.AudioSource | None = None

    @property
    def caller_identity(self) -> str:
        return self._caller_identity

    def start(self, attempt_id: UUID, sample_rate: int = 24000) -> None:
        self.stop("replaced")
        self._attempt_id = attempt_id
        self._task = asyncio.create_task(self._play(attempt_id, sample_rate))
        self._tasks.add(self._task)
        self._task.add_done_callback(self._tasks.discard)
        logger.info(
            "handoff_ringback_started",
            extra={"call_id": str(self._call_id), "attempt_id": str(attempt_id)},
        )

    def stop(self, reason: str, attempt_id: UUID | None = None) -> None:
        if self._attempt_id is None or (
            attempt_id is not None and attempt_id != self._attempt_id
        ):
            return
        old_id = self._attempt_id
        self._attempt_id = None
        if self._source is not None:
            self._source.clear_queue()
        if self._task is not None:
            self._task.cancel()
        logger.info(
            "handoff_ringback_stopped",
            extra={
                "call_id": str(self._call_id),
                "attempt_id": str(old_id),
                "stop_reason": reason,
            },
        )

    async def aclose(self) -> None:
        self.stop("session_shutdown")
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _play(self, attempt_id: UUID, sample_rate: int) -> None:
        source = rtc.AudioSource(sample_rate, 1, queue_size_ms=20)
        publication = None
        if self._attempt_id != attempt_id:
            await source.aclose()
            return
        self._source = source
        try:
            track = rtc.LocalAudioTrack.create_audio_track("handoff_ringback", source)
            publish = asyncio.create_task(
                self._room.local_participant.publish_track(
                    track,
                    rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_UNKNOWN),
                )
            )
            try:
                publication = await asyncio.shield(publish)
            except asyncio.CancelledError:
                publication = await publish
                raise
            while self._attempt_id == attempt_id:
                for offset in range(
                    0, int(sample_rate * TONE_SECONDS), int(sample_rate * FRAME_SECONDS)
                ):
                    if self._attempt_id != attempt_id:
                        return
                    await source.capture_frame(tone_frame(sample_rate, offset))
                await asyncio.sleep(SILENCE_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "handoff ringback playback failed",
                extra={"call_id": str(self._call_id), "attempt_id": str(attempt_id)},
            )
        finally:
            source.clear_queue()
            if self._source is source:
                self._source = None
            if publication is not None:
                await self._room.local_participant.unpublish_track(publication.sid)
            await source.aclose()
