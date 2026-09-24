import argparse
import asyncio
import hashlib
import sys
import time
import wave
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.artifacts import append, create, finish
from common.config import load_env, required
from common.metadata import manifest
from llm.run import request
from pipeline.first_chunk import FirstChunkTTS
from stt.run import measure as stt_measure
from tts.run import measure as tts_measure


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--min-sentence-chars", type=int, default=20)
    args = parser.parse_args()
    config = load_env()
    stt_key, stt_model, llm_endpoint, llm_key, llm_deployment, tts_model, voice = (
        required(
            config,
            "ELEVENLABS_API_KEY",
            "ELEVENLABS_STT_MODEL",
            "AZURE_LLM_ENDPOINT",
            "AZURE_LLM_API_KEY",
            "AZURE_LLM_DEPLOYMENT",
            "ELEVENLABS_TTS_MODEL",
            "ELEVENLABS_VOICE_ID",
        )
    )
    if stt_model != "scribe_v2_realtime":
        parser.error("cascade STT requires scribe_v2_realtime")
    with wave.open(str(args.audio)) as wav:
        rate = wav.getframerate()
        if (
            wav.getnchannels() != 1
            or wav.getsampwidth() != 2
            or rate not in (16000, 24000, 48000)
        ):
            parser.error("audio must be mono PCM16 WAV at 16, 24 or 48 kHz")
        pcm = wav.readframes(wav.getnframes())
    import httpx
    from openai import AsyncAzureOpenAI, AsyncOpenAI

    llm = (
        AsyncOpenAI(
            base_url=llm_endpoint.rstrip("/") + "/", api_key=llm_key, max_retries=0
        )
        if llm_endpoint.rstrip("/").endswith("/openai/v1")
        else AsyncAzureOpenAI(
            azure_endpoint=llm_endpoint,
            api_key=llm_key,
            azure_deployment=llm_deployment,
            api_version=required(config, "AZURE_LLM_API_VERSION")[0],
            max_retries=0,
        )
    )
    stt_uri = "wss://api.elevenlabs.io/v1/speech-to-text/realtime?" + urlencode(
        {
            "model_id": stt_model,
            "audio_format": f"pcm_{rate}",
            "commit_strategy": "manual",
            "language_code": "sk",
        }
    )
    tts_uri = (
        "https://api.elevenlabs.io/v1/text-to-dialogue/stream?output_format=mp3_22050_32"
        if tts_model.startswith("eleven_v3")
        else f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream?output_format=mp3_22050_32"
    )
    prompt = (
        Path(__file__).resolve().parents[2] / "llm/prompts/production.txt"
    ).read_text()
    path = create(
        __file__,
        manifest(
            "pipeline_cascade",
            "multiple",
            config.get("AZURE_LLM_MODEL"),
            llm_deployment,
            config.get("AGENT_REGION"),
            args.runs,
            0,
            {
                "audio_file": str(args.audio),
                "stt_model": stt_model,
                "tts_model": tts_model,
                "llm_to_tts": "LiveKit sentence tokenizer starts direct ElevenLabs TTS on first emitted chunk; model continues streaming",
                "min_sentence_chars": args.min_sentence_chars,
            },
        ),
    )
    rows = []
    async with httpx.AsyncClient(timeout=60) as http:
        for i in range(args.runs):
            start = time.perf_counter_ns()
            stt_start = time.perf_counter_ns()
            stt = await stt_measure(stt_uri, stt_key, pcm, rate, 60)
            stt_done = time.perf_counter_ns()
            row = {
                "run_index": i + 1,
                "warmup": False,
                "status": "ok",
                "stt_latency_ms": stt.get("audio_end_to_final_ms"),
                "stt_total_ms": stt["total_ms"],
                "stt_transcript": stt.get("transcript"),
            }
            if stt["status"] == "ok" and stt.get("transcript"):
                llm_start = time.perf_counter_ns()
                row["stt_to_llm_handoff_ms"] = (llm_start - stt_done) / 1e6
                first_chunk = FirstChunkTTS(
                    lambda text: tts_measure(
                        http, tts_uri, stt_key, tts_model, text, voice
                    ),
                    min_sentence_chars=args.min_sentence_chars,
                )
                llm_row, _ = await request(
                    llm,
                    llm_deployment,
                    prompt,
                    "warm",
                    hashlib.sha256(prompt.encode()).hexdigest()[:32],
                    "cascade",
                    i + 1,
                    False,
                    128,
                    None,
                    stt["transcript"],
                    on_text_delta=first_chunk.push,
                )
                tts = await first_chunk.finish()
                row.update(
                    llm_ttft_ms=llm_row.get("ttft_ms"),
                    llm_first_speakable_ms=(
                        (first_chunk.first_speakable_ns - llm_start) / 1e6
                        if first_chunk.first_speakable_ns is not None
                        else None
                    ),
                    llm_total_ms=llm_row["total_ms"],
                )
                if llm_row["status"] == "ok" and tts is not None:
                    tts_start = first_chunk.tts_start_ns
                    row.update(
                        tts_first_audio_ms=tts.get("first_audio_ms"),
                        tts_total_ms=tts["total_ms"],
                    )
                    if (
                        tts["status"] == "ok"
                        and tts.get("first_audio_ms") is not None
                        and tts_start is not None
                    ):
                        row["synthetic_pipeline_latency_ms"] = (
                            (tts_start - start) / 1e6
                            + tts["first_audio_ms"]
                            - (stt_start - start) / 1e6
                            - stt["last_audio_sent_ms"]
                        )
                    else:
                        row.update(status="error", error=tts.get("error"))
                else:
                    row.update(
                        status="error",
                        error=llm_row.get("error") or {"type": "EmptyLLMOutput"},
                    )
            else:
                row.update(
                    status="error",
                    error=stt.get("error") or {"type": "EmptyTranscript"},
                )
            row["total_ms"] = (time.perf_counter_ns() - start) / 1e6
            rows.append(row)
            append(path, "raw.jsonl", row)
            if row["status"] == "error":
                append(path, "errors.jsonl", row)
            print(
                f"[{i + 1:02}/{args.runs:02}] cascade first_audio={row.get('synthetic_pipeline_latency_ms')}ms {row['status']}"
            )
    finish(path, rows)
    await llm.close()


if __name__ == "__main__":
    asyncio.run(main())
