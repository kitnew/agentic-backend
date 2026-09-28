"""Provider-event cascade model for LiveKit 1.8.2 preemptive scheduling."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import wave
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from common.artifacts import append, create, finish
from common.config import load_env, required
from common.metadata import manifest
from llm.run import request
from pipeline.first_chunk import FirstChunkTTS
from stt.preflight import aggregate, equivalent
from stt.run import SONIOX_ENDPOINTS, measure_soniox
from tts.run import measure as tts_measure

from benchmarks.stt.diagnose_soniox import ObservedSocket
from benchmarks.stt.stable_prefix import StableFinalPrefix, threshold_leads


class Coordinator:
    """Mirror LiveKit's preflight replacement and transcript-only reuse rules."""

    def __init__(self, launch, enabled: bool):
        self.launch = launch
        self.enabled = enabled
        self.attempts = []
        self.current = None
        self.invalidations = 0
        self.restarts = 0
        self.reused = False
        self.turn_commit_ns = None

    def preflight(self, text: str, at_ns: int):
        if not self.enabled or not text.strip():
            return
        if self.current is not None:
            self.current["task"].cancel()
            self.current["cancelled_ns"] = at_ns
            self.current["cancellation_reason"] = "replacement"
            self.invalidations += 1
            self.current = None
        if len(self.attempts) >= 3:  # LiveKit 1.8.2 default max_retries.
            return
        self.current = self.launch(text, at_ns)
        self.attempts.append(self.current)
        self.restarts = len(self.attempts) - 1

    def commit(self, final: str, at_ns: int):
        self.turn_commit_ns = at_ns
        if self.current and equivalent(self.current["text"], final):
            self.reused = True
            self.current["gate"].set()
        elif self.current:
            self.current["task"].cancel()
            self.current["cancelled_ns"] = at_ns
            self.current["cancellation_reason"] = "final_mismatch"
            self.invalidations += 1
            self.current = None


async def trial(
    pcm,
    rate,
    key,
    region,
    llm,
    model,
    prompt,
    http,
    tts_uri,
    tts_key,
    tts_model,
    voice,
    index,
    max_tokens,
    mode,
):
    start = time.perf_counter_ns()
    preemptive = mode != "soniox_baseline"
    preemptive_tts = mode in (
        "soniox_preemptive_llm_tts",
        "soniox_stable_prefix_preemptive_llm_tts",
    )
    experimental = mode.startswith("soniox_stable_prefix_")

    def launch(text, at_ns):
        gate = asyncio.Event()
        if preemptive_tts:
            gate.set()
        attempt = {
            "text": text,
            "event_ns": at_ns,
            "start_ns": None,
            "gate": gate,
            "llm_done_ns": None,
            "cancelled_ns": None,
        }

        async def run():
            first_chunk = FirstChunkTTS(
                lambda chunk: tts_measure(
                    http, tts_uri, tts_key, tts_model, chunk, voice
                ),
                min_sentence_chars=20,
                gate=gate,
            )
            attempt["first_chunk"] = first_chunk
            try:
                attempt["start_ns"] = time.perf_counter_ns()
                llm_row, _ = await request(
                    llm,
                    model,
                    prompt,
                    "warm",
                    hashlib.sha256(prompt.encode()).hexdigest()[:32],
                    mode,
                    index,
                    False,
                    max_tokens,
                    None,
                    text,
                    service_tier="fast",
                    on_text_delta=first_chunk.push,
                )
                attempt["llm_done_ns"] = time.perf_counter_ns()
                tts_row = await first_chunk.finish()
                return llm_row, tts_row, first_chunk
            except asyncio.CancelledError:
                await first_chunk.aclose()
                raise

        attempt["task"] = asyncio.create_task(run())
        return attempt

    coordinator = Coordinator(launch, preemptive)
    provider_frames = []
    adapter = None

    def wrap_socket(ws, stream, start_ns):
        nonlocal adapter
        adapter = StableFinalPrefix(stream, start_ns) if experimental else None
        return ObservedSocket(
            ws,
            provider_frames,
            start_ns,
            on_frame=adapter.observe if adapter else None,
        )

    def audio_ended(at_ns):
        if adapter:
            adapter.audio_end_ns = at_ns

    stt_start = time.perf_counter_ns()
    stt = await measure_soniox(
        key,
        region,
        pcm,
        rate,
        60,
        on_preflight=coordinator.preflight,
        on_end=coordinator.commit,
        on_audio_end=audio_ended,
        socket_wrapper=wrap_socket,
    )
    experimental_preflights = (
        adapter.finish(stt.get("transcript", "")) if adapter else []
    )
    row = {
        "status": stt["status"],
        "variant": mode,
        "stt": stt,
        "transcript": stt.get("transcript", ""),
        "provider_frames": provider_frames,
        "experimental_preflights": experimental_preflights,
        "experimental_preflight_count": len(experimental_preflights),
        "first_stable_prefix_preflight_ms": (
            experimental_preflights[0]["timestamp_ms"]
            if experimental_preflights
            else None
        ),
        "first_preflight_lead_ms": (
            experimental_preflights[0]["preflight_lead_ms"]
            if experimental_preflights
            else None
        ),
        "first_preflight_word_count": (
            experimental_preflights[0]["stable_prefix_words"]
            if experimental_preflights
            else None
        ),
        "first_preflight_complete_word_count": (
            experimental_preflights[0]["complete_final_word_count"]
            if experimental_preflights
            else None
        ),
        "first_preflight_char_count": (
            experimental_preflights[0]["stable_prefix_chars"]
            if experimental_preflights
            else None
        ),
        "threshold_leads_ms": threshold_leads(
            experimental_preflights, stt.get("transcript", "")
        ),
        "preflight_count": stt.get("preflight_count", 0),
        "preflight_before_audio_end": stt.get("preflight_before_audio_end", False),
        "preflight_lead_time_ms": stt.get("preflight_lead_time_ms"),
        "speculative_attempt_count": len(coordinator.attempts),
        "speculative_attempt_reused": coordinator.reused,
        "speculative_attempt_invalidated": coordinator.invalidations > 0,
        "speculative_invalidation_count": coordinator.invalidations,
        "speculative_restart_count": coordinator.restarts,
        "speculative_tts_invalidated_count": sum(
            bool(item.get("first_chunk") and item["first_chunk"].tts_start_ns)
            for item in coordinator.attempts
            if item is not coordinator.current
        ),
    }
    if stt["status"] != "ok":
        row["error"] = stt.get("error")
        for old in coordinator.attempts:
            old["task"].cancel()
        await asyncio.gather(
            *(item["task"] for item in coordinator.attempts),
            return_exceptions=True,
        )
        return row
    audio_end_ns = stt_start + round(stt["logical_audio_end_ms"] * 1e6)
    row["logical_audio_end_ms"] = (audio_end_ns - start) / 1e6
    row["final_transcript_ms"] = (stt_start - start) / 1e6 + stt[
        "first_final_transcript_ms"
    ]
    row["first_preflight_ms"] = (
        (stt_start - start) / 1e6 + stt["first_preflight_ms"]
        if stt["first_preflight_ms"] is not None
        else None
    )
    row["turn_commit_ms"] = (
        (coordinator.turn_commit_ns or time.perf_counter_ns()) - start
    ) / 1e6
    attempt = (
        coordinator.current
        if coordinator.reused
        else launch(stt["transcript"], time.perf_counter_ns())
    )
    attempt["gate"].set()
    row["speculative_llm_start_ms"] = (
        (coordinator.attempts[0]["start_ns"] - start) / 1e6
        if coordinator.attempts and coordinator.attempts[0]["start_ns"] is not None
        else None
    )
    row["preemptive_lead_time_ms"] = (
        (audio_end_ns - coordinator.attempts[0]["start_ns"]) / 1e6
        if coordinator.attempts and coordinator.attempts[0]["start_ns"] is not None
        else None
    )
    try:
        llm_row, tts_row, first_chunk = await attempt["task"]
        row["committed_llm_start_ms"] = (
            (attempt["start_ns"] - start) / 1e6 if not coordinator.reused else None
        )
        if (
            llm_row["status"] != "ok"
            or not tts_row
            or tts_row["status"] != "ok"
            or tts_row.get("first_audio_ms") is None
        ):
            row.update(
                status="error",
                error=llm_row.get("error")
                or (tts_row or {}).get("error")
                or {"type": "EmptyTTS"},
            )
        else:
            row.update(
                first_llm_text_ms=(attempt["start_ns"] - start) / 1e6
                + llm_row["first_text_ms"],
                first_speakable_ms=(first_chunk.first_speakable_ns - start) / 1e6
                if first_chunk.first_speakable_ns
                else None,
                tts_start_ms=(first_chunk.tts_start_ns - start) / 1e6
                if first_chunk.tts_start_ns
                else None,
                first_tts_audio_ms=(first_chunk.tts_start_ns - start) / 1e6
                + tts_row["first_audio_ms"]
                if first_chunk.tts_start_ns
                and tts_row.get("first_audio_ms") is not None
                else None,
                llm_requested_service_tier=llm_row.get("requested_service_tier"),
                llm_response_service_tier=llm_row.get("response_service_tier"),
                llm_completion_ms=(attempt["llm_done_ns"] - start) / 1e6
                if attempt["llm_done_ns"]
                else None,
            )
            for field in ("first_llm_text", "first_speakable", "first_tts_audio"):
                value = row.get(field + "_ms")
                row["audio_end_to_" + field + "_ms"] = (
                    value - row["logical_audio_end_ms"] if value is not None else None
                )
            row["first_audio_eligible_lower_bound_ms"] = (
                max(row["turn_commit_ms"], row["first_tts_audio_ms"])
                if row["first_tts_audio_ms"] is not None
                else None
            )
            row["audio_end_to_first_audio_eligible_lower_bound_ms"] = (
                row["first_audio_eligible_lower_bound_ms"] - row["logical_audio_end_ms"]
                if row["first_audio_eligible_lower_bound_ms"] is not None
                else None
            )
            row["speculative_tts_start_ms"] = (
                row["tts_start_ms"] if preemptive_tts and coordinator.reused else None
            )
            row["first_speculative_tts_audio_ms"] = (
                row["first_tts_audio_ms"]
                if preemptive_tts and coordinator.reused
                else None
            )
    except Exception as exc:  # noqa: BLE001 - benchmark failures are data
        row.update(status="error", error={"type": type(exc).__name__})
    await asyncio.gather(
        *(item["task"] for item in coordinator.attempts if item is not attempt),
        return_exceptions=True,
    )

    def work_before_end(item):
        began = item["start_ns"]
        stopped = item["llm_done_ns"] or item["cancelled_ns"] or audio_end_ns
        return max(0, (min(audio_end_ns, stopped) - began) / 1e6) if began else 0

    row["llm_work_before_audio_end_ms"] = sum(
        work_before_end(item) for item in coordinator.attempts
    )
    row["reused_llm_work_before_audio_end_ms"] = (
        work_before_end(attempt) if coordinator.reused else 0
    )
    row["speculative_attempts"] = [
        {
            "event_ms": (item["event_ns"] - start) / 1e6,
            "llm_start_ms": (item["start_ns"] - start) / 1e6
            if item["start_ns"]
            else None,
            "llm_completion_ms": (item["llm_done_ns"] - start) / 1e6
            if item["llm_done_ns"]
            else None,
            "cancelled_ms": (item["cancelled_ns"] - start) / 1e6
            if item["cancelled_ns"]
            else None,
            "cancellation_reason": item.get("cancellation_reason"),
            "reused": item is attempt and coordinator.reused,
        }
        for item in coordinator.attempts
    ]
    row["preflight_intervals_ms"] = [
        right["timestamp_ms"] - left["timestamp_ms"]
        for left, right in pairwise(experimental_preflights)
    ]
    row["total_ms"] = (time.perf_counter_ns() - start) / 1e6
    return row


async def main():
    import httpx
    from openai import AsyncOpenAI

    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--max-output-tokens", type=int, default=512)
    parser.add_argument("--stable-final-prefix-preflight", action="store_true")
    parser.add_argument("--soniox-region", choices=tuple(SONIOX_ENDPOINTS))
    args = parser.parse_args()
    config = load_env()
    soniox_key = os.environ.get("BENCH_SONIOX_API_KEY") or config.get("SONIOX_API_KEY")
    if not soniox_key or soniox_key.startswith("YOUR_"):
        parser.error("Missing benchmark configuration: SONIOX_API_KEY")
    region = (
        args.soniox_region
        or (
            "eu"
            if args.stable_final_prefix_preflight
            else config.get("SONIOX_REGION", "global")
        )
    ).casefold()
    if region not in SONIOX_ENDPOINTS:
        parser.error("SONIOX_REGION must be GLOBAL/US or EU")
    tts_key, tts_model, voice, llm_key, model = required(
        config,
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_TTS_MODEL",
        "ELEVENLABS_VOICE_ID",
        "OPENAI_API_KEY",
        "OPENAI_LLM_MODEL",
    )
    if not tts_model.startswith("eleven_v3"):
        parser.error("Soniox comparison requires ElevenLabs v3 TTS")
    with wave.open(str(args.audio)) as wav:
        rate = wav.getframerate()
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or rate != 24000:
            parser.error("audio must be mono PCM16 WAV at 24 kHz")
        pcm = wav.readframes(wav.getnframes())
    prompt = (
        Path(__file__).resolve().parents[2] / "llm/prompts/production.txt"
    ).read_text()
    tts_uri = "https://api.elevenlabs.io/v1/text-to-dialogue/stream?output_format=mp3_22050_32"
    variants = (
        (
            "soniox_stock_preemptive_llm",
            "soniox_stable_prefix_preemptive_llm",
            "soniox_stable_prefix_preemptive_llm_tts",
        )
        if args.stable_final_prefix_preflight
        else ("soniox_baseline", "soniox_preemptive_llm", "soniox_preemptive_llm_tts")
    )
    path = create(
        __file__,
        manifest(
            "synthetic_preemptive",
            "soniox+openai+elevenlabs",
            model,
            model,
            region,
            args.runs,
            args.warmups,
            {
                "stt_model": "stt-rt-v5",
                "endpoint_class": "EU" if region == "eu" else "global",
                "audio_file": str(args.audio),
                "audio_duration_seconds": len(pcm) / (rate * 2),
                "sample_rate_hz": rate,
                "chunk_size_ms": 50,
                "audio_sha256": hashlib.sha256(pcm).hexdigest(),
                "llm_provider": "openai",
                "llm_model": model,
                "service_tier": "fast",
                "tts_provider": "elevenlabs",
                "tts_model": tts_model,
                "max_output_tokens": args.max_output_tokens,
                "variants": variants,
                "stable_final_prefix_preflight": args.stable_final_prefix_preflight,
                "turn_commit_model": "Soniox END_OF_SPEECH, not production local VAD",
            },
        ),
    )
    rows = []
    llm = AsyncOpenAI(api_key=llm_key, max_retries=0)
    try:
        async with httpx.AsyncClient(timeout=60) as http:
            for i in range(args.runs + args.warmups):
                for mode in variants:
                    row = await trial(
                        pcm,
                        rate,
                        soniox_key,
                        region,
                        llm,
                        model,
                        prompt,
                        http,
                        tts_uri,
                        tts_key,
                        tts_model,
                        voice,
                        i + 1,
                        args.max_output_tokens,
                        mode,
                    )
                    row.update(run_index=i + 1, warmup=i < args.warmups)
                    rows.append(row)
                    append(path, "raw.jsonl", row)
                    if row["status"] != "ok":
                        append(path, "errors.jsonl", row)
                    print(
                        f"[{i + 1}/{args.runs + args.warmups}] {mode}: {row['status']} preflights={row.get('experimental_preflight_count', 0)}",
                        flush=True,
                    )
    finally:
        await llm.close()
        summary = finish(path, rows)
        summary.update(aggregate(rows))
        (path / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
        )


if __name__ == "__main__":
    asyncio.run(main())
