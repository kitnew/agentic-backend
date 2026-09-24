import argparse
import asyncio
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.artifacts import append, create, finish
from common.config import load_env, required
from common.metadata import manifest

TEXTS = {
    "short": "Áno, samozrejme.",
    "normal": "Dobrý deň. Rada vám pomôžem s rezerváciou izby. Na aký dátum ju potrebujete?",
    "long": "Dobrý deň. Rada vám pomôžem s rezerváciou izby. Povedzte mi, prosím, dátum príchodu a odchodu, počet hostí a aký typ izby uprednostňujete. Potom spolu preveríme dostupnosť.",
}


async def measure(client, url, key, model, text, voice):
    start = time.perf_counter_ns()
    row = {
        "request_start_utc": datetime.now(UTC).isoformat(),
        "status": "ok",
        "first_audio_ms": None,
        "first_playable_audio_ms": None,
        "audio_bytes": 0,
    }
    audio = bytearray()
    try:
        async with client.stream(
            "POST",
            url,
            headers={"xi-api-key": key, "accept": "audio/mpeg"},
            json=(
                {
                    "inputs": [{"text": text, "voice_id": voice}],
                    "model_id": model,
                    "language_code": "sk",
                }
                if model.startswith("eleven_v3")
                else {"text": text, "model_id": model}
            ),
        ) as response:
            response.raise_for_status()
            row["http_status"] = response.status_code
            row["request_id"] = response.headers.get("request-id")
            async for chunk in response.aiter_bytes():
                if chunk:
                    row["first_audio_ms"] = (
                        row["first_audio_ms"] or (time.perf_counter_ns() - start) / 1e6
                    )
                    row["audio_bytes"] += len(chunk)
                    audio.extend(chunk)
            row["completion_ms"] = (time.perf_counter_ns() - start) / 1e6
            row["total_ms"] = row["completion_ms"]
            try:
                probe = await asyncio.to_thread(
                    subprocess.run,
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        "-i",
                        "pipe:0",
                    ],
                    input=bytes(audio),
                    capture_output=True,
                    timeout=10,
                    check=True,
                )
                row["audio_duration_ms"] = float(probe.stdout) * 1000
                row["real_time_factor"] = (
                    row["total_ms"] / row["audio_duration_ms"]
                    if row["audio_duration_ms"]
                    else None
                )
            except OSError, ValueError, subprocess.SubprocessError:
                row["audio_duration_ms"] = None
                row["real_time_factor"] = None
    except Exception as exc:  # noqa: BLE001 - record provider failures
        row.update(
            status="error",
            error={
                "type": type(exc).__name__,
                "status_code": getattr(exc, "status_code", None),
            },
            total_ms=(time.perf_counter_ns() - start) / 1e6,
        )
    return row


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=1)
    args = parser.parse_args()
    config = load_env()
    key, model, voice = required(
        config, "ELEVENLABS_API_KEY", "ELEVENLABS_TTS_MODEL", "ELEVENLABS_VOICE_ID"
    )
    import httpx

    url = (
        "https://api.elevenlabs.io/v1/text-to-dialogue/stream?output_format=mp3_22050_32"
        if model.startswith("eleven_v3")
        else f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream?output_format=mp3_22050_32"
    )
    path = create(
        __file__,
        manifest(
            "tts",
            "elevenlabs",
            model,
            None,
            config.get("ELEVENLABS_REGION"),
            args.runs * len(TEXTS),
            args.warmups * len(TEXTS),
            {
                "voice_id": voice,
                "output_format": "mp3_22050_32",
                "texts": TEXTS,
                "audio_duration": "ffprobe when installed; unavailable otherwise",
                "first_playable_boundary": "unavailable",
            },
        ),
    )
    rows = []
    async with httpx.AsyncClient(timeout=60) as client:
        for label, spoken in TEXTS.items():
            for i in range(args.runs + args.warmups):
                row = await measure(client, url, key, model, spoken, voice)
                row.update(
                    text_kind=label,
                    text=spoken,
                    run_index=i + 1,
                    warmup=i < args.warmups,
                    model=model,
                    voice_id=voice,
                )
                rows.append(row)
                append(path, "raw.jsonl", row)
                if row["status"] == "error":
                    append(path, "errors.jsonl", row)
                print(
                    f"[{i + 1:02}/{args.runs + args.warmups:02}] {label} first_audio={row['first_audio_ms']}ms {row['status']}"
                )
    finish(path, rows)


if __name__ == "__main__":
    asyncio.run(main())
