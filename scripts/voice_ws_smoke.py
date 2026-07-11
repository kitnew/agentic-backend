import asyncio
import base64
import json
import os
import urllib.request
from pathlib import Path

import websockets


DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_AUDIO_PATH = "app/sample.webm"


async def main() -> None:
    request = urllib.request.Request(
        os.getenv("API_URL", DEFAULT_API_URL) + "/api/v1/voice/sessions",
        data=json.dumps({"tenant_id": os.getenv("VOICE_TENANT_ID", "demo_restaurant")}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    session = json.load(urllib.request.urlopen(request))
    audio_path = Path(os.getenv("VOICE_WS_AUDIO_PATH", DEFAULT_AUDIO_PATH))
    audio_bytes = audio_path.read_bytes()
    midpoint = max(1, len(audio_bytes) // 2)

    async with websockets.connect(
        session["websocket_url"], subprotocols=["voice-session", session["session_token"]]
    ) as websocket:
        print(await websocket.recv())

        await websocket.send(json.dumps({"type": "ping"}))
        print(await websocket.recv())

        await websocket.send(audio_bytes[:midpoint])
        print(await websocket.recv())

        await websocket.send(
            json.dumps(
                {
                    "type": "audio_chunk",
                    "audio_base64": base64.b64encode(audio_bytes[midpoint:]).decode("ascii"),
                }
            )
        )
        print(await websocket.recv())

        await websocket.send(
            json.dumps(
                {
                    "type": "input_audio_commit",
                    "content_type": "audio/webm",
                    "filename": audio_path.name,
                }
            )
        )

        while True:
            event = json.loads(await websocket.recv())
            print(json.dumps(event, ensure_ascii=False))
            if event["type"] in {"turn_completed", "error"}:
                break

        await websocket.send(json.dumps({"type": "session_end"}))
        print(await websocket.recv())


if __name__ == "__main__":
    asyncio.run(main())
