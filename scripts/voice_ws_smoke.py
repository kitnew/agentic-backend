import asyncio
import base64
import json
import os
from pathlib import Path

import websockets


DEFAULT_URL = "ws://localhost:8000/api/v1/voice/stream?tenant_id=demo_restaurant"
DEFAULT_AUDIO_PATH = "app/sample.webm"


async def main() -> None:
    url = os.getenv("VOICE_WS_URL", DEFAULT_URL)
    audio_path = Path(os.getenv("VOICE_WS_AUDIO_PATH", DEFAULT_AUDIO_PATH))
    audio_bytes = audio_path.read_bytes()
    midpoint = max(1, len(audio_bytes) // 2)

    async with websockets.connect(url) as websocket:
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
