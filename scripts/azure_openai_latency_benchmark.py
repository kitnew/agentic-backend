#!/usr/bin/env python3
"""Sequential Azure OpenAI benchmark for the production voice request shape."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import statistics
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import openai as openai_sdk
from contracts import VoiceAgentRuntimeContext
from livekit.agents import llm
from livekit.agents.voice.generation import update_instructions
from livekit.plugins import openai
from voice_agent.backend import BackendClient
from voice_agent.main import assemble_instructions, build_agent_tools
from voice_agent.providers import azure_endpoint, llm_behavior_options
from voice_agent.settings import VoiceAgentSettings

DEFAULT_USER_TEXT = "Dobrý deň, aké informácie odo mňa potrebujete na rezerváciu izby?"
METRICS = (
    "first_raw_event_ms",
    "first_nonempty_text_ms",
    "first_20_text_chars_ms",
    "total_ms",
    "input_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "retries",
)
INTERLEAVED_ARMS = (
    ("A", "azure", "gpt-5.6-terra", "gpt-5.6-terra"),
    ("B", "openai", "gpt-5.6-terra", None),
    ("C", "azure", "gpt-5.6-luna", "gpt-5.6-luna"),
    ("D", "openai", "gpt-5.6-luna", None),
)


def percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def metric_stats(values: list[float]) -> dict[str, float | None]:
    return {
        f"p{percent}": percentile(values, percent) for percent in (50, 90, 95, 99)
    } | {
        "max": max(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


def prompt_cache_key(context: VoiceAgentRuntimeContext) -> str:
    stable_prefix = f"{context.prompt.system_prompt}\0{context.prompt.profile_prompt}"
    return "voice-agent-prompt:" + hashlib.sha256(stable_prefix.encode()).hexdigest()


def request_shape(
    context: VoiceAgentRuntimeContext,
    backend: BackendClient,
    user_text: str,
    cache_bust: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    instructions = assemble_instructions(context)
    cache_key = prompt_cache_key(context)
    if cache_bust:
        instructions = f"[benchmark-cache-bust:{cache_bust}]\n{instructions}"
        cache_key = f"benchmark-cache-bust:{cache_bust}"

    chat_ctx = llm.ChatContext.empty()
    update_instructions(
        chat_ctx, instructions=instructions, add_if_missing=True, modality="audio"
    )
    chat_ctx.add_message(role="assistant", content=[context.greeting])
    chat_ctx.add_message(role="user", content=[user_text])
    messages, _ = chat_ctx.to_provider_format(format="openai")
    tools = llm.ToolContext(
        build_agent_tools(context, backend, context.call_session_id)
    ).parse_function_tools("openai", strict=True)
    return messages, tools, cache_key


def frozen_request_shape(
    path: Path | None,
    generated: tuple[list[dict[str, Any]], list[dict[str, Any]], str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if path is None:
        return generated
    if path.exists():
        payload = json.loads(path.read_text())
        return payload["messages"], payload["tools"], payload["cache_key"]
    messages, tools, cache_key = generated
    path.write_text(
        json.dumps({"messages": messages, "tools": tools, "cache_key": cache_key})
        + "\n"
    )
    return generated


def provider(
    settings: VoiceAgentSettings,
    context: VoiceAgentRuntimeContext,
    backend: str,
    model: str,
    azure_deployment: str,
) -> openai.LLM:
    options = {
        "model": model,
        "timeout": httpx.Timeout(settings.provider_timeout_seconds),
        "max_completion_tokens": 256,
        **llm_behavior_options(context.voice_runtime),
    }
    if backend == "azure":
        return openai.LLM.with_azure(
            azure_deployment=azure_deployment,
            azure_endpoint=azure_endpoint(settings.azure_openai_endpoint),
            api_version=settings.azure_openai_api_version,
            api_key=settings.azure_openai_api_key.get_secret_value(),
            **options,
        )
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required for --backend openai")
    return openai.LLM(api_key=api_key, **options)


def safe_error(error: Exception) -> dict[str, Any]:
    return {
        "type": type(error).__name__,
        "status_code": getattr(error, "status_code", None),
        "request_id": getattr(error, "request_id", None),
    }


async def run_request(
    client: Any,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str,
    cache_key: str,
    service_tier: str,
    behavior: dict[str, object],
    timeout_seconds: float,
    retry_limit: int,
) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    first_raw = first_text = first_20 = None
    text = ""
    usage = None
    response_model = response_service_tier = region = None
    error: dict[str, Any] | None = None
    retries = 0
    raw_events = 0
    request_id = None
    tool_calls: dict[int, dict[str, str | None]] = {}

    for attempt in range(retry_limit + 1):
        try:
            stream = await client.chat.completions.create(
                messages=messages,
                tools=tools or openai_sdk.omit,
                model=model,
                stream_options={"include_usage": True},
                stream=True,
                timeout=httpx.Timeout(timeout_seconds),
                max_completion_tokens=256,
                prompt_cache_key=cache_key,
                service_tier=service_tier,
                **behavior,
            )
            region = stream.response.headers.get("x-ms-region")
            async with stream:
                async for chunk in stream:
                    elapsed = (time.perf_counter() - started) * 1000
                    raw_events += 1
                    first_raw = elapsed if first_raw is None else first_raw
                    request_id = chunk.id or request_id
                    response_model = chunk.model or response_model
                    response_service_tier = (
                        getattr(chunk, "service_tier", None) or response_service_tier
                    )
                    if chunk.usage is not None:
                        usage = chunk.usage
                    for choice in chunk.choices:
                        content = choice.delta.content or ""
                        if content and first_text is None:
                            first_text = elapsed
                        text += content
                        if len(text) >= 20 and first_20 is None:
                            first_20 = elapsed
                        for call in choice.delta.tool_calls or []:
                            current = tool_calls.setdefault(
                                call.index,
                                {"id": None, "name": None, "arguments": ""},
                            )
                            current["id"] = call.id or current["id"]
                            if call.function is not None:
                                current["name"] = call.function.name or current["name"]
                                current["arguments"] += call.function.arguments or ""
            error = None
            break
        except Exception as exc:  # noqa: BLE001 - production adapter retries provider failures
            error = safe_error(exc)
            if first_raw is not None or attempt == retry_limit:
                break
            retries += 1
            await asyncio.sleep(0.1 if attempt == 0 else 2.0)

    prompt_tokens = getattr(usage, "prompt_tokens", None)
    details = getattr(usage, "prompt_tokens_details", None)
    cached_tokens = getattr(details, "cached_tokens", None)
    return {
        "request_started_at": started_at,
        "first_raw_event_ms": first_raw,
        "first_nonempty_text_ms": first_text,
        "first_20_text_chars_ms": first_20,
        "total_ms": (time.perf_counter() - started) * 1000,
        "input_tokens": prompt_tokens,
        "cached_input_tokens": cached_tokens,
        "uncached_input_tokens": (
            prompt_tokens - cached_tokens
            if prompt_tokens is not None and cached_tokens is not None
            else None
        ),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "retries": retries,
        "error": error,
        "raw_events": raw_events,
        "response_chars": len(text),
        "response_text": text,
        "tool_calls": list(tool_calls.values()),
        "request_id": request_id,
        "response_model": response_model,
        "requested_service_tier": service_tier,
        "response_service_tier": response_service_tier,
        "azure_region": region,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[
            (
                row["provider"],
                row["requested_model"],
                row["workload"],
                row["requested_service_tier"],
            )
        ].append(row)
    output: dict[str, Any] = {}
    for (provider_name, model, workload, tier), group in groups.items():
        key = f"{provider_name}/{model}/{workload}/{tier}"
        output[key] = {
            "requests": len(group),
            "errors": sum(row["error"] is not None for row in group),
            **{
                metric: metric_stats(
                    [float(row[metric]) for row in group if row[metric] is not None]
                )
                for metric in METRICS
                if any(row[metric] is not None for row in group)
            },
        }
    return output


def summarize_interleaved(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latency_metrics = METRICS[:4]

    def groups(values: list[dict[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for arm in sorted({row["arm"] for row in values}):
            group = [row for row in values if row["arm"] == arm]
            output[arm] = {
                "provider": group[0]["provider"],
                "model": group[0]["requested_model"],
                "n": len(group),
                "errors": sum(row["error"] is not None for row in group),
                "retries": sum(row["retries"] for row in group),
                "cache_hits": sum(
                    (row["cached_input_tokens"] or 0) > 0 for row in group
                ),
                **{
                    metric: metric_stats(
                        [float(row[metric]) for row in group if row[metric] is not None]
                    )
                    for metric in latency_metrics
                },
            }
        return output

    return {
        "aggregate": groups(rows),
        "per_block": {
            str(block): groups([row for row in rows if row["block_number"] == block])
            for block in sorted({row["block_number"] for row in rows})
        },
    }


def calculator_probe_result(row: dict[str, Any]) -> dict[str, Any]:
    calls = row["tool_calls"]
    arguments = None
    try:
        arguments = json.loads(calls[0]["arguments"]) if len(calls) == 1 else None
    except json.JSONDecodeError:
        pass
    schema_valid = (
        isinstance(arguments, dict)
        and set(arguments) == {"operation", "operands"}
        and arguments["operation"]
        in {"add", "subtract", "multiply", "divide", "percentage"}
        and isinstance(arguments["operands"], list)
        and 2 <= len(arguments["operands"]) <= 10
        and all(isinstance(value, str) for value in arguments["operands"])
    )
    return {
        **row,
        "selected_calculator": len(calls) == 1 and calls[0]["name"] == "calculator",
        "arguments_json": arguments,
        "strict_schema_valid": schema_valid,
        "expected_operation": arguments
        == {
            "operation": "multiply",
            "operands": ["17", "23"],
        },
    }


async def load_context(
    args: argparse.Namespace, settings: VoiceAgentSettings, backend: BackendClient
) -> VoiceAgentRuntimeContext:
    if args.context_json:
        return VoiceAgentRuntimeContext.model_validate_json(
            args.context_json.read_text()
        )
    return await backend.runtime_context(args.call_id)


async def run_interleaved(
    args: argparse.Namespace,
    settings: VoiceAgentSettings,
    backend: BackendClient,
    context: VoiceAgentRuntimeContext,
) -> None:
    messages, tools, cache_key = frozen_request_shape(
        args.request_json,
        request_shape(context, backend, args.user_text, None),
    )
    workload_hash = hashlib.sha256(
        json.dumps(
            {"messages": messages, "tools": tools},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    clients: dict[str, openai.LLM] = {}
    warmups: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    block_times: list[dict[str, Any]] = []
    behavior = llm_behavior_options(context.voice_runtime)
    active_arms: list[tuple[str, str, str, str | None]] = []
    try:
        for arm, backend_name, model, deployment in INTERLEAVED_ARMS:
            try:
                clients[arm] = provider(
                    settings,
                    context,
                    backend_name,
                    model,
                    deployment or model,
                )
                for attempt in range(1, 6):
                    row = await run_request(
                        clients[arm]._client,
                        messages=messages,
                        tools=tools,
                        model=model,
                        cache_key=cache_key,
                        service_tier="default",
                        behavior=behavior,
                        timeout_seconds=settings.provider_timeout_seconds,
                        retry_limit=settings.provider_retry_limit,
                    )
                    row.update(
                        arm=arm,
                        provider=backend_name,
                        requested_model=model,
                        azure_deployment=deployment,
                        warmup_attempt=attempt,
                        workload_hash=workload_hash,
                    )
                    warmups.append(row)
                    if row["error"] is None and (row["cached_input_tokens"] or 0) > 0:
                        active_arms.append((arm, backend_name, model, deployment))
                        break
                else:
                    await clients[arm].aclose()
                    del clients[arm]
            except Exception as exc:  # noqa: BLE001 - isolate an unavailable arm
                warmups.append(
                    {
                        "arm": arm,
                        "provider": backend_name,
                        "requested_model": model,
                        "azure_deployment": deployment,
                        "error": safe_error(exc),
                        "workload_hash": workload_hash,
                    }
                )

        for block in range(1, args.interleaved_blocks + 1):
            block_started = datetime.now(UTC)
            for arm, backend_name, model, deployment in active_arms:
                for sequence in range(1, args.block_iterations + 1):
                    row = await run_request(
                        clients[arm]._client,
                        messages=messages,
                        tools=tools,
                        model=model,
                        cache_key=cache_key,
                        service_tier="default",
                        behavior=behavior,
                        timeout_seconds=settings.provider_timeout_seconds,
                        retry_limit=settings.provider_retry_limit,
                    )
                    row.update(
                        arm=arm,
                        provider=backend_name,
                        requested_model=model,
                        azure_deployment=deployment,
                        block_number=block,
                        block_sequence=sequence,
                        sequence_number=(block - 1) * args.block_iterations + sequence,
                        workload="warm",
                        workload_hash=workload_hash,
                        request_shape_sha256=workload_hash,
                        message_count=len(messages),
                        tool_count=len(tools),
                    )
                    rows.append(row)
                    print(json.dumps(row, separators=(",", ":")), flush=True)
            block_times.append(
                {
                    "block_number": block,
                    "started_at": block_started.isoformat(),
                    "ended_at": datetime.now(UTC).isoformat(),
                    "sequence": [arm for arm, *_ in active_arms],
                }
            )

        probe_messages = json.loads(json.dumps(messages))
        probe_messages[-1]["content"] = (
            "Použite nástroj calculator presne raz na výpočet 17 × 23. "
            "Nevypočítavajte to bez nástroja."
        )
        tool_probes = []
        for arm, backend_name, model, deployment in active_arms:
            row = await run_request(
                clients[arm]._client,
                messages=probe_messages,
                tools=tools,
                model=model,
                cache_key=cache_key,
                service_tier="default",
                behavior=behavior,
                timeout_seconds=settings.provider_timeout_seconds,
                retry_limit=settings.provider_retry_limit,
            )
            row.update(
                arm=arm,
                provider=backend_name,
                requested_model=model,
                azure_deployment=deployment,
            )
            tool_probes.append(calculator_probe_result(row))

        args.output_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "workload_hash": workload_hash,
            "arms": [
                {
                    "arm": arm,
                    "provider": backend_name,
                    "model": model,
                    "azure_deployment": deployment,
                }
                for arm, backend_name, model, deployment in active_arms
            ],
            "blocks": args.interleaved_blocks,
            "requests_per_arm_per_block": args.block_iterations,
            "concurrency": 1,
            "reasoning_effort": context.voice_runtime.llm.reasoning_effort,
            "max_completion_tokens": 256,
            "stream": True,
            "block_times": block_times,
        }
        (args.output_dir / "raw.json").write_text(
            json.dumps({"metadata": metadata, "results": rows}, indent=2) + "\n"
        )
        with (args.output_dir / "raw.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(
                {
                    **row,
                    "error": json.dumps(row["error"]),
                    "tool_calls": json.dumps(row["tool_calls"]),
                }
                for row in rows
            )
        (args.output_dir / "summary.json").write_text(
            json.dumps(summarize_interleaved(rows), indent=2) + "\n"
        )
        (args.output_dir / "warmup.json").write_text(
            json.dumps(warmups, indent=2) + "\n"
        )
        (args.output_dir / "tool_probe.json").write_text(
            json.dumps(tool_probes, indent=2) + "\n"
        )
    finally:
        for client in clients.values():
            await client.aclose()


async def async_main(args: argparse.Namespace) -> None:
    settings = VoiceAgentSettings()  # type: ignore[call-arg]
    backend = BackendClient(settings)
    llm_provider = None
    try:
        context = await load_context(args, settings, backend)
        if args.interleaved_blocks:
            await run_interleaved(args, settings, backend, context)
            return
        model = args.model or context.voice_runtime.llm.model
        azure_deployment = args.azure_deployment or settings.azure_openai_deployment
        llm_provider = provider(
            settings, context, args.backend, model, azure_deployment
        )
        rows: list[dict[str, Any]] = []
        warm_shape = frozen_request_shape(
            args.request_json,
            request_shape(context, backend, args.user_text, None),
        )
        workloads = (
            ("warm", "cache_busted") if args.workload == "both" else (args.workload,)
        )
        for tier in args.service_tier:
            for workload in workloads:
                for index in range(args.iterations):
                    messages, tools, cache_key = (
                        request_shape(
                            context, backend, args.user_text, uuid.uuid4().hex
                        )
                        if workload == "cache_busted"
                        else warm_shape
                    )
                    shape_hash = hashlib.sha256(
                        json.dumps(
                            {"messages": messages, "tools": tools},
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest()
                    row = await run_request(
                        llm_provider._client,
                        messages=messages,
                        tools=tools,
                        model=model,
                        cache_key=cache_key,
                        service_tier=tier,
                        behavior=llm_behavior_options(context.voice_runtime),
                        timeout_seconds=settings.provider_timeout_seconds,
                        retry_limit=settings.provider_retry_limit,
                    )
                    row.update(
                        workload=workload,
                        provider=args.backend,
                        requested_model=model,
                        iteration=index + 1,
                        request_shape_sha256=shape_hash,
                        message_count=len(messages),
                        tool_count=len(tools),
                    )
                    rows.append(row)
                    print(json.dumps(row, separators=(",", ":")), flush=True)

        args.output_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "provider": args.backend,
            "deployment": azure_deployment if args.backend == "azure" else None,
            "api_version": (
                settings.azure_openai_api_version if args.backend == "azure" else "v1"
            ),
            "requested_model": model,
            "reasoning_effort": context.voice_runtime.llm.reasoning_effort,
            "temperature": context.voice_runtime.llm.temperature,
            "max_completion_tokens": 256,
            "stream": True,
            "timeout_seconds": settings.provider_timeout_seconds,
            "retry_limit": settings.provider_retry_limit,
            "concurrency": 1,
            "call_session_id": str(context.call_session_id),
        }
        (args.output_dir / "raw.json").write_text(
            json.dumps({"metadata": metadata, "results": rows}, indent=2) + "\n"
        )
        with (args.output_dir / "raw.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows({**row, "error": json.dumps(row["error"])} for row in rows)
        (args.output_dir / "summary.json").write_text(
            json.dumps(summarize(rows), indent=2) + "\n"
        )
    finally:
        if llm_provider is not None:
            await llm_provider.aclose()
        await backend.aclose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--call-id", type=UUID)
    source.add_argument("--context-json", type=Path)
    parser.add_argument("--backend", choices=("azure", "openai"), default="azure")
    parser.add_argument("--model")
    parser.add_argument("--azure-deployment")
    parser.add_argument("--request-json", type=Path)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--interleaved-blocks", type=int, default=0)
    parser.add_argument("--block-iterations", type=int, default=10)
    parser.add_argument(
        "--workload", choices=("warm", "cache_busted", "both"), default="both"
    )
    parser.add_argument(
        "--service-tier", action="append", choices=("default", "priority"), default=[]
    )
    parser.add_argument("--user-text", default=DEFAULT_USER_TEXT)
    parser.add_argument("--output-dir", type=Path, default=Path("azure-llm-benchmark"))
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")
    if args.interleaved_blocks < 0 or args.block_iterations < 1:
        parser.error("interleaved counts must be positive")
    if args.interleaved_blocks and not args.request_json:
        parser.error("--interleaved-blocks requires --request-json")
    if args.request_json and args.workload != "warm":
        parser.error("--request-json requires --workload warm")
    args.service_tier = args.service_tier or ["default"]
    return args


if __name__ == "__main__":
    asyncio.run(async_main(parse_args()))
