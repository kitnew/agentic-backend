import argparse
import asyncio
import base64
import hashlib
import json
import os
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
from stt.preflight import aggregate, metrics

SONIOX_ENDPOINTS = {
    "global": "wss://stt-rt.soniox.com/transcribe-websocket",
    "us": "wss://stt-rt.soniox.com/transcribe-websocket",
    "global/us": "wss://stt-rt.soniox.com/transcribe-websocket",
    "eu": "wss://stt-rt.eu.soniox.com/transcribe-websocket",
}


def soniox_endpoint(region: str) -> str:
    return SONIOX_ENDPOINTS[region.casefold()]


async def measure_soniox(
    key: str,
    region: str,
    pcm: bytes,
    rate: int,
    timeout: float,
    on_preflight=None,
    on_end=None,
    on_audio_end=None,
    socket_wrapper=None,
) -> dict:
    import aiohttp
    from livekit import rtc
    from livekit.agents import stt as livekit_stt
    from livekit.plugins import soniox

    start = time.perf_counter_ns()
    row = {
        "status": "ok",
        "connection_start_ms": 0.0,
        "preflights": [],
        "transcript": "",
    }
    try:
        async with aiohttp.ClientSession() as session:
            provider = soniox.STT(
                api_key=key,
                base_url=soniox_endpoint(region),
                http_session=session,
                params=soniox.STTOptions(
                    model="stt-rt-v5", language_hints=["sk"], sample_rate=rate
                ),
            )
            stream = provider.stream()
            connect = stream._connect_ws

            async def timed_connect():
                ws = await connect()
                row["connection_ready_ms"] = (time.perf_counter_ns() - start) / 1e6
                row["connection_ms"] = row["connection_ready_ms"]
                return socket_wrapper(ws, stream, start) if socket_wrapper else ws

            stream._connect_ws = timed_connect
            receiver = None
            try:

                async def receive():
                    async for event in stream:
                        elapsed = (time.perf_counter_ns() - start) / 1e6
                        kind = event.type
                        value = event.alternatives[0].text if event.alternatives else ""
                        if (
                            kind == livekit_stt.SpeechEventType.INTERIM_TRANSCRIPT
                            and value
                        ):
                            row.setdefault("first_interim_transcript_ms", elapsed)
                            row.setdefault("first_partial_ms", elapsed)
                        elif (
                            kind == livekit_stt.SpeechEventType.PREFLIGHT_TRANSCRIPT
                            and value
                        ):
                            row["preflights"].append(
                                {"elapsed_ms": elapsed, "text": value}
                            )
                            row.setdefault("first_partial_ms", elapsed)
                            row.setdefault("first_preflight_transcript_ms", elapsed)
                            if on_preflight:
                                on_preflight(value, time.perf_counter_ns())
                        elif kind == livekit_stt.SpeechEventType.FINAL_TRANSCRIPT:
                            row.setdefault("first_final_transcript_ms", elapsed)
                            row["transcript"] += value
                        elif kind == livekit_stt.SpeechEventType.END_OF_SPEECH:
                            row.setdefault("end_of_speech_event_ms", elapsed)
                            if on_end:
                                on_end(row["transcript"], time.perf_counter_ns())
                            return

                receiver = asyncio.create_task(receive())
                chunk_bytes = rate * 2 // 20
                row["first_audio_sent_ms"] = (time.perf_counter_ns() - start) / 1e6
                for offset in range(0, len(pcm), chunk_bytes):
                    chunk = pcm[offset : offset + chunk_bytes]
                    stream.push_frame(rtc.AudioFrame(chunk, rate, 1, len(chunk) // 2))
                    await asyncio.sleep(len(chunk) / (rate * 2))
                row["last_audio_sent_ms"] = (time.perf_counter_ns() - start) / 1e6
                row["logical_audio_end_ms"] = row["last_audio_sent_ms"]
                if on_audio_end:
                    on_audio_end(time.perf_counter_ns())
                await asyncio.wait_for(receiver, timeout)
                if not row["transcript"].strip():
                    raise RuntimeError("empty_transcript")
                row["completion_ms"] = (time.perf_counter_ns() - start) / 1e6
                row["first_final_ms"] = row["first_final_transcript_ms"]
                row["audio_end_to_final_ms"] = (
                    row["first_final_ms"] - row["logical_audio_end_ms"]
                )
                row["total_ms"] = row["completion_ms"]
                row.update(
                    metrics(
                        row["preflights"],
                        row["transcript"],
                        row["logical_audio_end_ms"],
                    )
                )
            finally:
                if receiver is not None:
                    if not receiver.done():
                        receiver.cancel()
                    await asyncio.gather(receiver, return_exceptions=True)
                await stream.aclose()
    except Exception as exc:  # noqa: BLE001 - provider errors are benchmark data
        row.update(
            status="error",
            error={"type": type(exc).__name__},
            total_ms=(time.perf_counter_ns() - start) / 1e6,
        )
    return row


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
                        if (
                            row.get("last_audio_sent_ms") is not None
                            and row["first_partial_after_audio_end_ms"] is None
                        ):
                            row["first_partial_after_audio_end_ms"] = elapsed
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
            if not row["transcript"].strip():
                raise RuntimeError("empty_transcript")
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
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument(
        "--provider", choices=("elevenlabs", "soniox"), default="elevenlabs"
    )
    args = parser.parse_args()
    config = load_env()
    if args.provider == "soniox":
        key = os.environ.get("BENCH_SONIOX_API_KEY") or config.get("SONIOX_API_KEY")
        if not key or key.startswith("YOUR_"):
            parser.error("Missing benchmark configuration: SONIOX_API_KEY")
        model = "stt-rt-v5"
        region = config.get("SONIOX_REGION", "global").casefold()
        if region not in SONIOX_ENDPOINTS:
            parser.error("SONIOX_REGION must be GLOBAL/US or EU")
    else:
        key, model = required(config, "ELEVENLABS_API_KEY", "ELEVENLABS_STT_MODEL")
        region = config.get("ELEVENLABS_REGION")
    if args.provider == "elevenlabs" and model != "scribe_v2_realtime":
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
            args.provider,
            model,
            None,
            region,
            args.runs,
            args.warmups,
            {
                "audio_file": str(args.audio),
                "audio_duration_seconds": duration,
                "audio_sha256": hashlib.sha256(pcm).hexdigest(),
                "sample_rate_hz": rate,
                "channels": 1,
                "encoding": "pcm16",
                "mode": "realtime websocket, paced 50ms chunks",
                "chunk_size_ms": 50,
                "endpoint_class": "EU"
                if region == "eu"
                else "global"
                if args.provider == "soniox"
                else None,
            },
        ),
    )
    rows = []
    for i in range(args.runs + args.warmups):
        row = (
            await measure_soniox(key, region, pcm, rate, args.timeout)
            if args.provider == "soniox"
            else await measure(uri, key, pcm, rate, args.timeout)
        )
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
    summary = finish(path, rows)
    if args.provider == "soniox":
        summary.update(aggregate(rows))
        (path / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
        )


if __name__ == "__main__":
    asyncio.run(main())
