import argparse
import asyncio
import base64
import hashlib
import json
import sys
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.artifacts import append, create, finish
from common.config import load_env, required
from common.metadata import manifest


async def measure(uri: str, key: str, pcm: bytes, rate: int, timeout: float) -> dict:
    import websockets

    start = time.perf_counter_ns()
    row = {
        "request_start_utc": datetime.now(UTC).isoformat(),
        "status": "ok",
        "first_partial_ms": None,
        "first_partial_after_audio_end_ms": None,
        "first_final_ms": None,
        "transcript": "",
    }
    try:
        async with websockets.connect(
            uri, additional_headers={"xi-api-key": key}, open_timeout=timeout
        ) as ws:
            row["connection_ms"] = (time.perf_counter_ns() - start) / 1e6

            async def receive():
                while True:
                    message = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                    elapsed = (time.perf_counter_ns() - start) / 1e6
                    kind = message.get("message_type")
                    if kind == "partial_transcript" and message.get("text"):
                        row["first_partial_ms"] = row["first_partial_ms"] or elapsed
                        if row.get("last_audio_sent_ms") is not None:
                            row["first_partial_after_audio_end_ms"] = (
                                row["first_partial_after_audio_end_ms"] or elapsed
                            )
                    if kind == "committed_transcript":
                        row["first_final_ms"] = row["first_final_ms"] or elapsed
                        row["transcript"] += message.get("text", "")
                        return
                    if kind in ("error", "auth_error", "quota_exceeded"):
                        raise RuntimeError(kind)

            receiver = asyncio.create_task(receive())
            chunk_bytes = rate * 2 // 20
            row["first_audio_sent_ms"] = (time.perf_counter_ns() - start) / 1e6
            for offset in range(0, len(pcm), chunk_bytes):
                chunk = pcm[offset : offset + chunk_bytes]
                await ws.send(
                    json.dumps(
                        {
                            "message_type": "input_audio_chunk",
                            "audio_base_64": base64.b64encode(chunk).decode(),
                            "commit": False,
                            "sample_rate": rate,
                        }
                    )
                )
                await asyncio.sleep(len(chunk) / (rate * 2))
            row["last_audio_sent_ms"] = (time.perf_counter_ns() - start) / 1e6
            await ws.send(
                json.dumps(
                    {
                        "message_type": "input_audio_chunk",
                        "audio_base_64": "",
                        "commit": True,
                        "sample_rate": rate,
                    }
                )
            )
            row["commit_sent_ms"] = (time.perf_counter_ns() - start) / 1e6
            await receiver
            row["completion_ms"] = (time.perf_counter_ns() - start) / 1e6
            row["audio_end_to_final_ms"] = (
                row["first_final_ms"] - row["last_audio_sent_ms"]
            )
            row["audio_end_to_first_partial_ms"] = (
                row["first_partial_after_audio_end_ms"] - row["last_audio_sent_ms"]
                if row["first_partial_after_audio_end_ms"] is not None
                else None
            )
            row["total_ms"] = row["completion_ms"]
    except Exception as exc:  # noqa: BLE001 - record provider failures
        row.update(
            status="error",
            error={"type": type(exc).__name__},
            total_ms=(time.perf_counter_ns() - start) / 1e6,
        )
    return row


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    config = load_env()
    key, model = required(config, "ELEVENLABS_API_KEY", "ELEVENLABS_STT_MODEL")
    if model != "scribe_v2_realtime":
        parser.error("This streaming benchmark requires scribe_v2_realtime")
    with wave.open(str(args.audio)) as wav:
        rate = wav.getframerate()
        if (
            wav.getnchannels() != 1
            or wav.getsampwidth() != 2
            or rate not in (16000, 24000, 48000)
        ):
            parser.error("audio must be mono PCM16 WAV at 16, 24 or 48 kHz")
        pcm, duration = wav.readframes(wav.getnframes()), wav.getnframes() / rate
    uri = "wss://api.elevenlabs.io/v1/speech-to-text/realtime?" + urlencode(
        {
            "model_id": model,
            "audio_format": f"pcm_{rate}",
            "commit_strategy": "manual",
            "language_code": "sk",
        }
    )
    path = create(
        __file__,
        manifest(
            "stt",
            "elevenlabs",
            model,
            None,
            config.get("ELEVENLABS_REGION"),
            args.runs,
            args.warmups,
            {
                "audio_file": str(args.audio),
                "audio_duration_seconds": duration,
                "audio_sha256": hashlib.sha256(pcm).hexdigest(),
                "sample_rate_hz": rate,
                "encoding": "pcm16",
                "mode": "realtime websocket, paced 50ms chunks",
            },
        ),
    )
    rows = []
    for i in range(args.runs + args.warmups):
        row = await measure(uri, key, pcm, rate, args.timeout)
        row.update(
            run_index=i + 1,
            warmup=i < args.warmups,
            model=model,
            audio_duration_seconds=duration,
            sample_rate_hz=rate,
            encoding="pcm16",
        )
        rows.append(row)
        append(path, "raw.jsonl", row)
        if row["status"] == "error":
            append(path, "errors.jsonl", row)
        print(
            f"[{i + 1:02}/{args.runs + args.warmups:02}] STT final={row.get('first_final_ms')}ms {row['status']}"
        )
    finish(path, rows)


if __name__ == "__main__":
    asyncio.run(main())
