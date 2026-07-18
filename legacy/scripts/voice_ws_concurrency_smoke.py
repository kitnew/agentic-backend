import asyncio
import base64
import json
import os
import time
import urllib.request
from pathlib import Path

import websockets


DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_AUDIO_PATH = "app/sample.webm"


async def run_turn(name: str, session: dict, audio_bytes: bytes, filename: str) -> list[dict]:
    midpoint = max(1, len(audio_bytes) // 2)
    events = []
    async with websockets.connect(
        session["websocket_url"], subprotocols=["voice-session", session["session_token"]]
    ) as websocket:
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
    sessions = []
    for _ in range(2):
        request = urllib.request.Request(
            os.getenv("API_URL", DEFAULT_API_URL) + "/api/v1/voice/sessions",
            data=json.dumps({"tenant_id": os.getenv("VOICE_TENANT_ID", "demo_restaurant")}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        sessions.append(json.load(urllib.request.urlopen(request)))
    audio_path = Path(os.getenv("VOICE_WS_AUDIO_PATH", DEFAULT_AUDIO_PATH))
    audio_bytes = audio_path.read_bytes()

    started = time.perf_counter()
    first_events, second_events = await asyncio.gather(
        run_turn("first", sessions[0], audio_bytes, audio_path.name),
        run_turn("second", sessions[1], audio_bytes, audio_path.name),
    )
    elapsed = time.perf_counter() - started

    print(f"elapsed_seconds={elapsed:.3f}")
    for label, events in [("first", first_events), ("second", second_events)]:
        print(label)
        for event in events:
            print(json.dumps(event, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
