import argparse
import asyncio
import hashlib
import random
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.artifacts import append, create, finish
from common.config import load_env, required
from common.metadata import manifest

USER_TEXT = "Dobrý deň, aké informácie odo mňa potrebujete na rezerváciu izby?"


def cache_state(cached: int | None, intended: str) -> str:
    if cached is None:
        return "unavailable"
    if cached > 0:
        return "confirmed_hit"
    return "confirmed_miss" if intended == "cold" else "warm_intended_miss"


def safe_error(exc: Exception) -> dict:
    return {
        "type": type(exc).__name__,
        "status_code": getattr(exc, "status_code", None),
        "request_id": getattr(exc, "request_id", None),
    }


async def request(
    client,
    deployment: str,
    prompt: str,
    mode: str,
    namespace: str,
    scenario: str,
    index: int,
    warmup: bool,
    max_tokens: int,
    temperature: float | None,
    user_text: str = USER_TEXT,
    service_tier: str = "default",
    on_text_delta: Callable[[str, int], None] | None = None,
) -> tuple[dict, list[dict]]:
    marker = f"[cache namespace {namespace}]\n"
    started = time.perf_counter_ns()
    row = {
        "scenario": scenario,
        "run_index": index,
        "warmup": warmup,
        "request_start_utc": datetime.now(UTC).isoformat(),
        "cache_intent": mode,
        "status": "ok",
        "first_response_event_ms": None,
        "first_text_ms": None,
        "ttft_ms": None,
        "first_speakable_ms": None,
        "cached_input_tokens": None,
        "requested_service_tier": service_tier,
        "response_service_tier": None,
        "response_model": None,
    }
    events = []
    text = ""
    usage = None
    try:
        stream = await client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": marker + prompt},
                {"role": "user", "content": user_text},
            ],
            stream=True,
            stream_options={"include_usage": True},
            max_completion_tokens=max_tokens,
            prompt_cache_key="benchmark:" + namespace,
            service_tier=service_tier,
            **({"temperature": temperature} if temperature is not None else {}),
        )
        response = getattr(stream, "response", None)
        headers = getattr(response, "headers", {})
        row["request_id"] = headers.get("x-request-id") or headers.get(
            "apim-request-id"
        )
        row["provider_region"] = headers.get("x-ms-region")
        async for chunk in stream:
            now = time.perf_counter_ns()
            elapsed = (now - started) / 1e6
            row["first_response_event_ms"] = row["first_response_event_ms"] or elapsed
            row["request_id"] = getattr(chunk, "_request_id", None) or row.get(
                "request_id"
            )
            events.append(
                {
                    "elapsed_ms": elapsed,
                    "event": "chunk",
                    "id": chunk.id,
                    "choices": len(chunk.choices),
                }
            )
            if chunk.usage:
                usage = chunk.usage
            row["response_service_tier"] = (
                getattr(chunk, "service_tier", None) or row["response_service_tier"]
            )
            row["response_model"] = (
                getattr(chunk, "model", None) or row["response_model"]
            )
            for choice in chunk.choices:
                delta = choice.delta.content or ""
                if delta:
                    if on_text_delta is not None:
                        on_text_delta(delta, now)
                    row["first_text_ms"] = row["first_text_ms"] or elapsed
                    text += delta
                    if row["first_speakable_ms"] is None and any(
                        char in text for char in ".!?…"
                    ):
                        row["first_speakable_ms"] = elapsed
        row["ttft_ms"] = row["first_text_ms"]
        if row["ttft_ms"] is None:
            raise RuntimeError("response_completed_without_text")
        row["response_completion_ms"] = (time.perf_counter_ns() - started) / 1e6
        row["total_ms"] = row["response_completion_ms"]
        row["input_tokens"] = getattr(usage, "prompt_tokens", None)
        row["output_tokens"] = getattr(usage, "completion_tokens", None)
        details = getattr(usage, "prompt_tokens_details", None)
        row["cached_input_tokens"] = getattr(details, "cached_tokens", None)
        row["cache_state"] = cache_state(row["cached_input_tokens"], mode)
        row["output_chars"] = len(text)
        row["output_text"] = text
        row["output_tokens_per_second"] = (
            row["output_tokens"] * 1000 / (row["total_ms"] - row["first_text_ms"])
            if row["output_tokens"]
            and row["first_text_ms"] is not None
            and row["total_ms"] > row["first_text_ms"]
            else None
        )
    except Exception as exc:  # noqa: BLE001 - capture provider failures as benchmark data
        row["status"] = "error"
        row["error"] = safe_error(exc)
        row["total_ms"] = (time.perf_counter_ns() - started) / 1e6
        row["cache_state"] = "unavailable"
    return row, events


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--max-output-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--provider", choices=("azure", "openai"), default="azure")
    parser.add_argument("--service-tier", default="default")
    parser.add_argument(
        "--prompts", choices=("minimal", "production", "both"), default="both"
    )
    parser.add_argument("--production-prompt", type=Path)
    args = parser.parse_args()
    if args.runs < 1 or args.warmups < 0:
        parser.error("runs must be positive and warmups nonnegative")
    allowed = {
        "azure": {"default", "priority"},
        "openai": {"default", "fast", "priority", "flex", "ultrafast"},
    }
    if args.service_tier not in allowed[args.provider]:
        parser.error(f"unsupported {args.provider} service tier: {args.service_tier}")
    if args.prompts != "minimal" and not args.production_prompt:
        parser.error("--production-prompt is required for production measurements")
    config = load_env()
    if args.provider == "azure":
        endpoint, key, deployment = required(
            config, "AZURE_LLM_ENDPOINT", "AZURE_LLM_API_KEY", "AZURE_LLM_DEPLOYMENT"
        )
    else:
        key, deployment = required(config, "OPENAI_API_KEY", "OPENAI_LLM_MODEL")
    from openai import AsyncAzureOpenAI, AsyncOpenAI

    if args.provider == "openai":
        client = AsyncOpenAI(api_key=key, max_retries=0, timeout=60)
    elif endpoint.rstrip("/").endswith("/openai/v1"):
        client = AsyncOpenAI(
            base_url=endpoint.rstrip("/") + "/", api_key=key, max_retries=0, timeout=60
        )
    else:
        client = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_key=key,
            azure_deployment=deployment,
            api_version=required(config, "AZURE_LLM_API_VERSION")[0],
            max_retries=0,
            timeout=60,
        )
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
    prompt_hashes = {
        name: hashlib.sha256(prompts[name].encode()).hexdigest() for name in names
    }
    path = create(
        __file__,
        manifest(
            "llm",
            "azure_openai" if args.provider == "azure" else "openai",
            config.get("AZURE_LLM_MODEL") if args.provider == "azure" else deployment,
            deployment,
            config.get("AZURE_LLM_REGION")
            if args.provider == "azure"
            else "provider_routed",
            args.runs * len(names) * 2,
            args.warmups * len(names) * 2,
            {
                "max_output_tokens": args.max_output_tokens,
                "temperature": args.temperature,
                "user_text": USER_TEXT,
                "prompt_sha256": prompt_hashes,
                "production_prompt_file": str(args.production_prompt)
                if args.production_prompt
                else None,
                "requested_service_tier": args.service_tier,
                "scenario_order": "shuffled within each round; seed 42",
                "cache_method": "unique equal-length leading namespace per cold request; identical leading namespace for warm requests",
            },
        ),
    )
    rows = []
    scenarios = [(name, mode) for name in names for mode in ("cold", "warm")]
    warm_namespaces = {
        name: hashlib.sha256(f"{path}:{name}".encode()).hexdigest()[:32]
        for name, mode in scenarios
        if mode == "warm"
    }
    rng = random.Random(42)
    for i in range(args.warmups + args.runs):
        order = scenarios.copy()
        rng.shuffle(order)
        for prompt_name, mode in order:
            scenario = f"{prompt_name}_{mode}"
            namespace = (
                uuid.uuid4().hex if mode == "cold" else warm_namespaces[prompt_name]
            )
            row, events = await request(
                client,
                deployment,
                prompts[prompt_name],
                mode,
                namespace,
                scenario,
                i + 1,
                i < args.warmups,
                args.max_output_tokens,
                args.temperature,
                service_tier=args.service_tier,
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
                f"[{i + 1:02}/{args.warmups + args.runs:02}] {scenario} TTFT={row['ttft_ms']}ms total={row['total_ms']:.1f}ms cached={row['cached_input_tokens']} {row['status']}"
            )
    finish(path, rows)
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
