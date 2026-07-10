import asyncio
import base64
import json
import os
import time
from pathlib import Path

import websockets


DEFAULT_URL = "ws://localhost:8000/api/v1/voice/stream?tenant_id=demo_restaurant"
DEFAULT_AUDIO_PATH = "app/sample.webm"


async def run_turn(name: str, url: str, audio_bytes: bytes, filename: str) -> list[dict]:
    midpoint = max(1, len(audio_bytes) // 2)
    events = []
    async with websockets.connect(url) as websocket:
        events.append(json.loads(await websocket.recv()))
        await websocket.send(audio_bytes[:midpoint])
        events.append(json.loads(await websocket.recv()))
        await websocket.send(
            json.dumps(
                {
                    "type": "audio_chunk",
                    "audio_base64": base64.b64encode(audio_bytes[midpoint:]).decode("ascii"),
                }
            )
        )
        events.append(json.loads(await websocket.recv()))
        await websocket.send(
            json.dumps(
                {
                    "type": "input_audio_commit",
                    "content_type": "audio/webm",
                    "filename": filename,
                    "metadata": {"smoke_session": name},
                }
            )
        )
        while True:
            event = json.loads(await websocket.recv())
            events.append(event)
            if event["type"] in {"turn_completed", "error"}:
                break
    return events


async def main() -> None:
    url = os.getenv("VOICE_WS_URL", DEFAULT_URL)
    audio_path = Path(os.getenv("VOICE_WS_AUDIO_PATH", DEFAULT_AUDIO_PATH))
    audio_bytes = audio_path.read_bytes()

    started = time.perf_counter()
    first_events, second_events = await asyncio.gather(
        run_turn("first", url, audio_bytes, audio_path.name),
        run_turn("second", url, audio_bytes, audio_path.name),
    )
    elapsed = time.perf_counter() - started

    print(f"elapsed_seconds={elapsed:.3f}")
    for label, events in [("first", first_events), ("second", second_events)]:
        print(label)
        for event in events:
            print(json.dumps(event, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
