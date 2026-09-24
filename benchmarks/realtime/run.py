import argparse
import asyncio
import base64
import hashlib
import json
import random
import sys
import time
import wave
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.artifacts import append, create, finish
from common.config import load_env, required
from common.metadata import manifest


def ws_url(endpoint: str, deployment: str, api_version: str | None) -> str:
    parsed = urlparse(endpoint)
    path = parsed.path.rstrip("/")
    if path.endswith("/openai/v1"):
        path += "/realtime"
        api_version = None
    elif path in ("", "/openai"):
        path = "/openai/realtime" if api_version else "/openai/v1/realtime"
    query = (
        {"model": deployment}
        if not api_version
        else {"deployment": deployment, "api-version": api_version}
    )
    if parsed.scheme not in ("https", "wss"):
        raise ValueError("Realtime endpoint must use https:// or wss://")
    return urlunparse(
        (
            "wss",
            parsed.netloc,
            path,
            "",
            urlencode(query),
            "",
        )
    )


def safe_error(exc: Exception, key: str) -> dict:
    response = getattr(exc, "response", None)
    body = getattr(response, "body", b"") or b""
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    redact = lambda value: value.replace(key, "[redacted]") if key else value
    return {
        "type": type(exc).__name__,
        "status_code": getattr(response, "status_code", None),
        "reason_phrase": redact(str(getattr(response, "reason_phrase", "")))[:500],
        "body": redact(str(body))[:500],
        "detail": redact(str(exc))[:500],
    }


def audio_bytes(path: Path) -> tuple[bytes, float]:
    with wave.open(str(path)) as wav:
        if (
            wav.getnchannels() != 1
            or wav.getsampwidth() != 2
            or wav.getframerate() != 24000
        ):
            raise SystemExit("Realtime requires mono PCM16 WAV at 24000 Hz")
        return wav.readframes(wav.getnframes()), wav.getnframes() / 24000


def derive(events: list[dict]) -> dict:
    times = {}
    for event in events:
        times.setdefault(event["event"], event["elapsed_ms"])

    def delta(end, start):
        return times[end] - times[start] if end in times and start in times else None

    # Azure legacy responses use the shorter audio/text event names.
    for old, new in (
        ("response.audio.delta", "response.output_audio.delta"),
        ("response.audio_transcript.delta", "response.output_audio_transcript.delta"),
        ("response.text.delta", "response.output_text.delta"),
    ):
        if old in times and new not in times:
            times[new] = times[old]
    return {
        "ws_connect_ms": delta("ws_connected", "connection_start"),
        "session_init_ms": delta("session.updated", "session_update_sent"),
        "input_end_to_first_audio_ms": delta(
            "response.output_audio.delta", "last_input_audio_sent"
        ),
        "commit_to_response_created_ms": delta(
            "response.created", "input_audio_buffer.commit_sent"
        ),
        "input_end_to_first_text_ms": (
            delta("response.output_text.delta", "last_input_audio_sent")
            or delta("response.output_audio_transcript.delta", "last_input_audio_sent")
        ),
        "input_end_to_completion_ms": delta("response.done", "last_input_audio_sent"),
    }


async def trial(
    ws,
    pcm: bytes,
    prompt: str,
    origin: int,
    timeout: float,
    configure_session: bool = True,
    key: str = "",
    modality: str = "audio",
    on_text_delta: Callable[[str, int], None] | None = None,
) -> tuple[dict, list[dict]]:
    events = []
    output_text = ""

    def mark(name: str, **extra):
        events.append(
            {
                "event": name,
                "elapsed_ms": (time.perf_counter_ns() - origin) / 1e6,
                **extra,
            }
        )

    async def send(payload: dict, name: str):
        await ws.send(json.dumps(payload))
        mark(name)

    async def receive_until(target: str):
        nonlocal output_text
        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            kind = event.get("type", "unknown")
            mark(
                kind,
                event_id=event.get("event_id"),
                response_id=(event.get("response") or {}).get("id"),
                session_model=(event.get("session") or {}).get("model"),
                error_code=(event.get("error") or {}).get("code"),
                error_message=str(
                    (event.get("error") or {}).get("message") or ""
                ).replace(key, "[redacted]")
                if key
                else (event.get("error") or {}).get("message"),
            )
            if kind in (
                "response.output_text.delta",
                "response.output_audio_transcript.delta",
                "response.text.delta",
                "response.audio_transcript.delta",
            ):
                delta = event.get("delta", "")
                output_text += delta
                if delta and on_text_delta is not None:
                    on_text_delta(delta, time.perf_counter_ns())
            if kind == "error":
                raise RuntimeError(
                    str((event.get("error") or {}).get("code", "provider_error"))
                )
            if kind == target:
                return event

    row = {
        "request_start_utc": datetime.now(UTC).isoformat(),
        "status": "ok",
        "cache_state": "unsupported",
    }
    try:
        if configure_session:
            await send(
                {
                    "type": "session.update",
                    "session": {
                        "type": "realtime",
                        "instructions": prompt,
                        "output_modalities": [modality],
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcm", "rate": 24000},
                                "turn_detection": None,
                            },
                            "output": {
                                "format": {"type": "audio/pcm", "rate": 24000},
                                "voice": "alloy",
                            },
                        },
                    },
                },
                "session_update_sent",
            )
            await receive_until("session.updated")
        mark("first_input_audio")
        # Send the fixed file as one logical input. Upload time is captured separately.
        await send(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm).decode(),
            },
            "last_input_audio_sent",
        )
        await send(
            {"type": "input_audio_buffer.commit"}, "input_audio_buffer.commit_sent"
        )
        await send({"type": "response.create"}, "response.create_sent")
        completed = await receive_until("response.done")
        if (completed.get("response") or {}).get("status") != "completed":
            raise RuntimeError(
                str(
                    (completed.get("response") or {}).get("status_details")
                    or "response_incomplete"
                )
            )
        usage = (completed.get("response") or {}).get("usage") or {}
        row.update(derive(events))
        if modality == "audio" and row["input_end_to_first_audio_ms"] is None:
            raise RuntimeError("response_completed_without_audio")
        if modality == "text" and not output_text:
            raise RuntimeError("response_completed_without_text")
        row["input_tokens"] = usage.get("input_tokens")
        row["cached_input_tokens"] = (usage.get("input_token_details") or {}).get(
            "cached_tokens"
        )
        row["output_tokens"] = usage.get("output_tokens")
        if row["cached_input_tokens"] is not None:
            row["cache_state"] = (
                "confirmed_hit" if row["cached_input_tokens"] > 0 else "confirmed_miss"
            )
        row["output_text"] = output_text
        row["total_ms"] = events[-1]["elapsed_ms"]
    except Exception as exc:  # noqa: BLE001 - capture provider failures as benchmark data
        row["status"] = "error"
        row["error"] = safe_error(exc, key)
        row["total_ms"] = (time.perf_counter_ns() - origin) / 1e6
    return row, events


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--provider", choices=("azure", "openai"), default="azure")
    parser.add_argument(
        "--prompts", choices=("minimal", "production", "both"), default="both"
    )
    parser.add_argument("--production-prompt", type=Path)
    parser.add_argument(
        "--session-mode", choices=("fresh", "continued", "both"), default="both"
    )
    args = parser.parse_args()
    if args.runs < 1 or args.warmups < 0:
        parser.error("runs must be positive and warmups nonnegative")
    if args.prompts != "minimal" and not args.production_prompt:
        parser.error("--production-prompt is required for production measurements")
    config = load_env()
    if args.provider == "azure":
        endpoint, key, deployment = required(
            config,
            "AZURE_REALTIME_ENDPOINT",
            "AZURE_REALTIME_API_KEY",
            "AZURE_REALTIME_DEPLOYMENT",
        )
        uri = ws_url(endpoint, deployment, config.get("AZURE_REALTIME_API_VERSION"))
        headers = {"api-key": key}
    else:
        key, deployment = required(config, "OPENAI_API_KEY", "OPENAI_REALTIME_MODEL")
        uri = f"wss://api.openai.com/v1/realtime?{urlencode({'model': deployment})}"
        headers = {"Authorization": f"Bearer {key}"}
    pcm, duration = audio_bytes(args.audio)
    import websockets

    prompts = {
        "minimal": (Path(__file__).parent / "prompts" / "minimal.txt").read_text()
    }
    if args.production_prompt:
        prompts["production"] = args.production_prompt.read_text()
        if not prompts["production"].strip():
            parser.error(
                "production prompt file is empty; add captured effective instructions or use --prompts minimal"
            )
    names = ("minimal", "production") if args.prompts == "both" else (args.prompts,)
    modes = (
        ("fresh", "continued") if args.session_mode == "both" else (args.session_mode,)
    )
    prompt_hashes = {
        name: hashlib.sha256(prompts[name].encode()).hexdigest() for name in names
    }
    path = create(
        __file__,
        manifest(
            "realtime",
            "azure_openai" if args.provider == "azure" else "openai",
            config.get("AZURE_REALTIME_MODEL")
            if args.provider == "azure"
            else deployment,
            deployment,
            config.get("AZURE_REALTIME_REGION")
            if args.provider == "azure"
            else "provider_routed",
            args.runs * len(names) * len(modes),
            args.warmups * len(names) * len(modes),
            {
                "audio_file": str(args.audio),
                "audio_duration_seconds": duration,
                "audio_sha256": hashlib.sha256(pcm).hexdigest(),
                "prompt_sha256": prompt_hashes,
                "input_mode": "single append, manual commit; no paced playback or server VAD",
                "production_prompt_file": str(args.production_prompt)
                if args.production_prompt
                else None,
                "session_modes": "fresh opens a new connection; continued keeps conversation history",
                "scenario_order": "shuffled within each round; seed 42",
            },
        ),
    )
    rows = []
    scenarios = [(name, mode) for name in names for mode in modes]
    sessions = {}
    rng = random.Random(42)
    try:
        for i in range(args.warmups + args.runs):
            order = scenarios.copy()
            rng.shuffle(order)
            for prompt_name, mode in order:
                scenario = f"{prompt_name}_{mode}"
                origin = time.perf_counter_ns()
                events = [{"event": "turn_start", "elapsed_ms": 0.0}]
                ws = sessions.get(scenario)
                new_session = ws is None
                try:
                    if new_session:
                        events.append({"event": "connection_start", "elapsed_ms": 0.0})
                        ws = await websockets.connect(
                            uri,
                            additional_headers=headers,
                            open_timeout=args.timeout,
                            max_size=16 * 1024 * 1024,
                        )
                        events.append(
                            {
                                "event": "ws_connected",
                                "elapsed_ms": (time.perf_counter_ns() - origin) / 1e6,
                            }
                        )
                        if mode == "continued":
                            sessions[scenario] = ws
                    row, trial_events = await trial(
                        ws,
                        pcm,
                        prompts[prompt_name],
                        origin,
                        args.timeout,
                        configure_session=new_session,
                        key=key,
                    )
                    events.extend(trial_events)
                    row.update(derive(events))
                except Exception as exc:  # noqa: BLE001 - capture provider failures as benchmark data
                    row = {
                        "status": "error",
                        "error": safe_error(exc, key),
                        "total_ms": (time.perf_counter_ns() - origin) / 1e6,
                        "cache_state": "unavailable",
                    }
                finally:
                    if mode == "fresh" and ws is not None:
                        await ws.close()
                row.update(
                    {
                        "scenario": scenario,
                        "run_index": i + 1,
                        "warmup": i < args.warmups,
                        "session_mode": mode,
                        "new_session": new_session,
                    }
                )
                rows.append(row)
                append(path, "raw.jsonl", row)
                for event in events:
                    append(
                        path,
                        "events.jsonl",
                        {
                            "scenario": scenario,
                            "run_index": i + 1,
                            "warmup": row["warmup"],
                            **event,
                        },
                    )
                if row["status"] == "error":
                    append(path, "errors.jsonl", row)
                print(
                    f"[{i + 1:02}/{args.warmups + args.runs:02}] {scenario} first_audio={row.get('input_end_to_first_audio_ms')}ms total={row['total_ms']:.1f}ms {row['status']}"
                )
                if row["status"] == "error":
                    finish(path, rows)
                    raise SystemExit(
                        "Realtime benchmark stopped after first failure; inspect errors.jsonl"
                    )
    finally:
        for ws in sessions.values():
            await ws.close()
    finish(path, rows)


if __name__ == "__main__":
    asyncio.run(main())
