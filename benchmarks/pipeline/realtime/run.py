import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.artifacts import append, create, finish
from common.config import load_env, required
from common.metadata import manifest
from realtime.run import audio_bytes, derive, trial, ws_url


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--audio", type=Path, required=True)
    args = parser.parse_args()
    config = load_env()
    endpoint, key, deployment = required(
        config,
        "AZURE_REALTIME_ENDPOINT",
        "AZURE_REALTIME_API_KEY",
        "AZURE_REALTIME_DEPLOYMENT",
    )
    pcm, duration = audio_bytes(args.audio)
    import websockets

    uri = ws_url(endpoint, deployment, config.get("AZURE_REALTIME_API_VERSION"))
    prompt = (
        Path(__file__).resolve().parents[2] / "realtime/prompts/production.txt"
    ).read_text()
    path = create(
        __file__,
        manifest(
            "pipeline_realtime",
            "azure_openai",
            config.get("AZURE_REALTIME_MODEL"),
            deployment,
            config.get("AZURE_REALTIME_REGION"),
            args.runs,
            0,
            {
                "audio_file": str(args.audio),
                "audio_duration_seconds": duration,
                "input_mode": "single append, manual commit",
            },
        ),
    )
    rows = []
    for i in range(args.runs):
        origin = time.perf_counter_ns()
        events = [{"event": "connection_start", "elapsed_ms": 0.0}]
        try:
            async with websockets.connect(
                uri, additional_headers={"api-key": key}, max_size=16 * 1024 * 1024
            ) as ws:
                events.append(
                    {
                        "event": "ws_connected",
                        "elapsed_ms": (time.perf_counter_ns() - origin) / 1e6,
                    }
                )
                row, stage_events = await trial(ws, pcm, prompt, origin, 60)
                events.extend(stage_events)
                row.update(derive(events))
        except Exception as exc:  # noqa: BLE001 - record provider failure
            row = {
                "status": "error",
                "error": {"type": type(exc).__name__},
                "total_ms": (time.perf_counter_ns() - origin) / 1e6,
            }
        row.update(run_index=i + 1, warmup=False)
        rows.append(row)
        append(path, "raw.jsonl", row)
        for event in events:
            append(path, "events.jsonl", {"run_index": i + 1, **event})
        if row["status"] == "error":
            append(path, "errors.jsonl", row)
        print(
            f"[{i + 1:02}/{args.runs:02}] realtime first_audio={row.get('input_end_to_first_audio_ms')}ms {row['status']}"
        )
    finish(path, rows)


if __name__ == "__main__":
    asyncio.run(main())
