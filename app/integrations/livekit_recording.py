import asyncio
import base64
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path

from livekit import api


TERMINAL_STATUSES = {
    "EGRESS_COMPLETE",
    "EGRESS_FAILED",
    "EGRESS_ABORTED",
    "EGRESS_LIMIT_REACHED",
}


@dataclass(frozen=True)
class RecordingSettings:
    api_url: str
    api_key: str
    api_secret: str
    output_dir: Path
    timeout_seconds: float = 20.0
    poll_seconds: float = 0.5

    @classmethod
    def from_env(cls) -> "RecordingSettings":
        livekit_url = os.getenv("LIVEKIT_INTERNAL_URL", "ws://livekit:7880")
        api_url = livekit_url.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
        return cls(
            api_url=api_url,
            api_key=os.getenv("LIVEKIT_API_KEY", "").strip(),
            api_secret=os.getenv("LIVEKIT_API_SECRET", "").strip(),
            output_dir=Path(os.getenv("LIVEKIT_RECORDING_DIR", "/recordings")),
            timeout_seconds=float(os.getenv("LIVEKIT_RECORDING_TIMEOUT_SECONDS", "20")),
            poll_seconds=float(os.getenv("LIVEKIT_RECORDING_POLL_SECONDS", "0.5")),
        )


@dataclass(frozen=True)
class RecordingHandle:
    egress_id: str
    room_name: str
    path: Path


def recording_path(output_dir: Path, call_session_id: str) -> Path:
    return output_dir / f"{call_session_id}.ogg"


def status_name(status: int | str) -> str:
    if isinstance(status, str):
        return status
    return api.EgressStatus.Name(status)


async def start_room_recording(
    room_name: str,
    call_session_id: str,
    *,
    client=None,
    settings: RecordingSettings | None = None,
) -> RecordingHandle:
    settings = settings or RecordingSettings.from_env()
    owned_client = client is None
    if owned_client and (not settings.api_key or not settings.api_secret):
        raise RuntimeError("LiveKit recording credentials are not configured")
    client = client or api.LiveKitAPI(
        url=settings.api_url,
        api_key=settings.api_key,
        api_secret=settings.api_secret,
    )
    path = recording_path(settings.output_dir, call_session_id)
    try:
        existing = await client.egress.list_egress(api.ListEgressRequest(room_name=room_name))
        if existing.items:
            return RecordingHandle(existing.items[0].egress_id, room_name, path)
        info = await client.egress.start_room_composite_egress(
            api.RoomCompositeEgressRequest(
                room_name=room_name,
                audio_only=True,
                file_outputs=[
                    api.EncodedFileOutput(
                        file_type=api.EncodedFileType.OGG,
                        filepath=str(path),
                        disable_manifest=True,
                    )
                ],
            )
        )
        return RecordingHandle(info.egress_id, room_name, path)
    finally:
        if owned_client:
            await client.aclose()


async def stop_and_wait_recording(
    handle: RecordingHandle,
    *,
    client=None,
    settings: RecordingSettings | None = None,
) -> object:
    settings = settings or RecordingSettings.from_env()
    owned_client = client is None
    client = client or api.LiveKitAPI(
        url=settings.api_url,
        api_key=settings.api_key,
        api_secret=settings.api_secret,
    )
    try:
        await client.egress.stop_egress(api.StopEgressRequest(egress_id=handle.egress_id))
        return await wait_for_recording(handle, client=client, settings=settings)
    finally:
        if owned_client:
            await client.aclose()


async def wait_for_recording(
    handle: RecordingHandle,
    *,
    client,
    settings: RecordingSettings | None = None,
) -> object:
    settings = settings or RecordingSettings.from_env()

    async def poll():
        while True:
            response = await client.egress.list_egress(
                api.ListEgressRequest(egress_id=handle.egress_id)
            )
            if not response.items:
                raise RuntimeError(f"Egress not found: {handle.egress_id}")
            info = response.items[0]
            current = status_name(info.status)
            if current in TERMINAL_STATUSES:
                if current != "EGRESS_COMPLETE":
                    raise RuntimeError(
                        f"Egress {handle.egress_id} ended with {current}: {info.error or info.details}"
                    )
                return info
            await asyncio.sleep(settings.poll_seconds)

    return await asyncio.wait_for(poll(), timeout=settings.timeout_seconds)


def save_base64_file(handle: RecordingHandle) -> dict[str, str]:
    # ponytail: shared local volume for the first rollout; add S3 upload when external retention is required.
    encoded_path = handle.path.with_suffix(handle.path.suffix + ".base64.txt")
    encoded_path.write_text(base64.b64encode(handle.path.read_bytes()).decode("ascii"), encoding="ascii")
    return {
        "filename": handle.path.name,
        "content_type": mimetypes.guess_type(handle.path.name)[0] or "audio/ogg",
        "base64_file": str(encoded_path),
    }
