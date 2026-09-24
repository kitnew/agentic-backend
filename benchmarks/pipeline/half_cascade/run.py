import argparse
import asyncio
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.artifacts import append, create, finish
from common.config import load_env, required
from common.metadata import manifest
from pipeline.first_chunk import FirstChunkTTS
from realtime.run import audio_bytes, derive, trial, ws_url
from stt.run import measure as stt_measure
from tts.run import measure as tts_measure


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--audio", type=Path, required=True)
    args = parser.parse_args()
    config = load_env()
    endpoint, key, deployment, tts_key, stt_model, tts_model, voice = required(
        config,
        "AZURE_REALTIME_ENDPOINT",
        "AZURE_REALTIME_API_KEY",
        "AZURE_REALTIME_DEPLOYMENT",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_STT_MODEL",
        "ELEVENLABS_TTS_MODEL",
        "ELEVENLABS_VOICE_ID",
    )
    pcm, duration = audio_bytes(args.audio)
    if stt_model != "scribe_v2_realtime":
        parser.error("half-cascade standalone STT requires scribe_v2_realtime")
    stt_uri = "wss://api.elevenlabs.io/v1/speech-to-text/realtime?" + urlencode(
        {
            "model_id": stt_model,
            "audio_format": "pcm_24000",
            "commit_strategy": "manual",
            "language_code": "sk",
        }
    )
    import httpx
    import websockets

    uri = ws_url(endpoint, deployment, config.get("AZURE_REALTIME_API_VERSION"))
    tts_uri = (
        "https://api.elevenlabs.io/v1/text-to-dialogue/stream?output_format=mp3_22050_32"
        if tts_model.startswith("eleven_v3")
        else f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream?output_format=mp3_22050_32"
    )
    prompt = (
        Path(__file__).resolve().parents[2] / "realtime/prompts/production.txt"
    ).read_text()
    path = create(
        __file__,
        manifest(
            "pipeline_half_cascade",
            "azure_openai+elevenlabs",
            config.get("AZURE_REALTIME_MODEL"),
            deployment,
            config.get("AGENT_REGION"),
            args.runs,
            0,
            {
                "audio_file": str(args.audio),
                "audio_duration_seconds": duration,
                "architecture": "Realtime audio input, parallel standalone ElevenLabs STT, text output, ElevenLabs TTS",
                "text_to_tts": "LiveKit default sentence tokenizer starts ElevenLabs TTS on first emitted text chunk",
            },
        ),
    )
    rows = []
    async with httpx.AsyncClient(timeout=60) as http:
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
                    stt_task = asyncio.create_task(
                        stt_measure(stt_uri, tts_key, pcm, 24000, 60)
                    )
                    first_chunk = FirstChunkTTS(
                        lambda text: tts_measure(
                            http, tts_uri, tts_key, tts_model, text, voice
                        )
                    )
                    row, stage_events = await trial(
                        ws,
                        pcm,
                        prompt,
                        origin,
                        60,
                        modality="text",
                        on_text_delta=first_chunk.push,
                    )
                    events.extend(stage_events)
                    row.update(derive(events))
                tts = await first_chunk.finish()
                if row["status"] == "ok" and tts is not None:
                    tts_start = first_chunk.tts_start_ns
                    row["first_speakable_ms"] = (
                        (first_chunk.first_speakable_ns - origin) / 1e6
                        if first_chunk.first_speakable_ns is not None
                        else None
                    )
                    row.update(
                        tts_first_audio_ms=tts.get("first_audio_ms"),
                        tts_total_ms=tts["total_ms"],
                    )
                    if (
                        tts["status"] == "ok"
                        and tts.get("first_audio_ms") is not None
                        and tts_start is not None
                    ):
                        row["input_end_to_first_audio_ms"] = (
                            (tts_start - origin) / 1e6
                            + tts["first_audio_ms"]
                            - next(
                                event["elapsed_ms"]
                                for event in events
                                if event["event"] == "last_input_audio_sent"
                            )
                        )
                    else:
                        row.update(status="error", error=tts.get("error"))
                else:
                    row.update(
                        status="error",
                        error=row.get("error") or {"type": "EmptyRealtimeText"},
                    )
                stt = await stt_task
                row.update(
                    standalone_stt_status=stt["status"],
                    standalone_stt_total_ms=stt["total_ms"],
                    standalone_stt_final_ms=stt.get("first_final_ms"),
                    standalone_stt_transcript=stt.get("transcript"),
                )
            except Exception as exc:  # noqa: BLE001 - record provider failure
                row = {"status": "error", "error": {"type": type(exc).__name__}}
            row["total_ms"] = (time.perf_counter_ns() - origin) / 1e6
            row.update(run_index=i + 1, warmup=False)
            rows.append(row)
            append(path, "raw.jsonl", row)
            for event in events:
                append(path, "events.jsonl", {"run_index": i + 1, **event})
            if row["status"] == "error":
                append(path, "errors.jsonl", row)
            print(
                f"[{i + 1:02}/{args.runs:02}] half_cascade first_audio={row.get('input_end_to_first_audio_ms')}ms {row['status']}"
            )
    finish(path, rows)


if __name__ == "__main__":
    asyncio.run(main())
