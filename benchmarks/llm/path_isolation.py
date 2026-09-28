"""Isolate historical standalone and synthetic-cascade LLM request paths."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.artifacts import append, finish
from common.config import load_env, required
from common.metadata import manifest
from common.stats import summarize
from llm.run import USER_TEXT, request

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT = (
    "Dobrý deň, chcel by som si rezervovať dvojložkovú izbu od dvadsiateho "
    "piateho do dvadsiateho šiesteho septembra."
)
VARIANTS = (
    "STANDALONE_EXISTING",
    "DIRECT_CASCADE_PAYLOAD",
    "LIVEKIT_LLM_DIRECT",
    "CASCADE_LLM_EXISTING",
)
FIELDS = (
    "api_type",
    "model",
    "deployment",
    "requested_service_tier",
    "reasoning_effort",
    "effective_reasoning_setting",
    "max_completion_tokens",
    "max_tokens",
    "temperature",
    "top_p",
    "stream",
    "response_format",
    "parallel_tool_calls",
    "tool_choice",
    "tools",
    "messages",
    "instructions",
    "history_count",
    "metadata",
    "prompt_cache_key",
    "prompt_cache_retention",
    "previous_response_id",
    "timeout",
    "max_retries",
    "extra_header_names",
    "prompt_chars",
    "prompt_bytes",
    "estimated_input_tokens",
    "prompt_sha256",
    "user_sha256",
    "tool_schema_count",
    "tool_schema_bytes",
)


def normalize(kwargs, *, model, timeout, max_retries):
    messages = kwargs.get("messages", [])
    system = "\n".join(
        str(m.get("content", ""))
        for m in messages
        if m.get("role") in ("system", "developer")
    )
    user = "\n".join(
        str(m.get("content", "")) for m in messages if m.get("role") == "user"
    )
    tools = kwargs.get("tools")
    if not isinstance(tools, list):
        tools = []
    out = {key: None for key in FIELDS}
    out.update(
        api_type="chat.completions",
        model=kwargs.get("model", model),
        deployment=None,
        requested_service_tier=kwargs.get("service_tier"),
        reasoning_effort=kwargs.get("reasoning_effort", "omitted"),
        max_completion_tokens=kwargs.get("max_completion_tokens"),
        max_tokens=kwargs.get("max_tokens"),
        temperature=kwargs.get("temperature"),
        top_p=kwargs.get("top_p"),
        stream=kwargs.get("stream"),
        response_format=kwargs.get("response_format"),
        parallel_tool_calls=kwargs.get("parallel_tool_calls"),
        tool_choice=kwargs.get("tool_choice"),
        tools=[
            {
                "name": tool.get("function", {}).get("name"),
                "sha256": hashlib.sha256(
                    json.dumps(tool, sort_keys=True, default=str).encode()
                ).hexdigest(),
            }
            for tool in tools
        ],
        messages=[
            {
                "role": m.get("role"),
                "content_sha256": hashlib.sha256(
                    str(m.get("content", "")).encode()
                ).hexdigest(),
                "content_chars": len(str(m.get("content", ""))),
            }
            for m in messages
        ],
        instructions=None,
        history_count=max(0, len(messages) - 2),
        metadata=sorted(kwargs["metadata"])
        if isinstance(kwargs.get("metadata"), dict)
        else None,
        prompt_cache_key=kwargs.get("prompt_cache_key"),
        prompt_cache_retention=kwargs.get("prompt_cache_retention"),
        previous_response_id=kwargs.get("previous_response_id"),
        timeout=str(kwargs.get("timeout", timeout)),
        max_retries=max_retries,
        extra_header_names=sorted(kwargs.get("extra_headers", {})),
        prompt_chars=len(system),
        prompt_bytes=len(system.encode()),
        prompt_sha256=hashlib.sha256(system.encode()).hexdigest(),
        user_sha256=hashlib.sha256(user.encode()).hexdigest(),
        tool_schema_count=len(tools),
        tool_schema_bytes=len(json.dumps(tools, default=str).encode()),
    )
    return out


def diff_requests(left, right):
    return {
        key: {
            "status": "unobservable"
            if key in ("effective_reasoning_setting", "estimated_input_tokens")
            else "same"
            if left.get(key) == right.get(key)
            else "missing in standalone"
            if left.get(key) is None
            else "missing in cascade"
            if right.get(key) is None
            else "different",
            "standalone": left.get(key),
            "cascade": right.get(key),
        }
        for key in FIELDS
    }


def usage_values(usage):
    if usage is None:
        return {
            key: None
            for key in (
                "input_tokens",
                "cached_tokens",
                "output_tokens",
                "reasoning_tokens",
                "returned_tier",
            )
        }
    prompt = getattr(usage, "prompt_tokens_details", None)
    completion = getattr(usage, "completion_tokens_details", None)
    return {
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "cached_tokens": getattr(prompt, "cached_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "reasoning_tokens": getattr(completion, "reasoning_tokens", None),
        "returned_tier": getattr(usage, "service_tier", None),
    }


def event_kind(chunk):
    if chunk.usage:
        return "usage"
    if any(getattr(choice.delta, "content", None) for choice in chunk.choices):
        return "text"
    return "non_text"


def stages(ns):
    def delta(a, b):
        return (
            (ns[b] - ns[a]) / 1e6
            if ns.get(a) is not None and ns.get(b) is not None
            else None
        )

    return {
        "pre_invoke_ms": delta("T0", "T2"),
        "request_build_ms": delta("T0", "T1"),
        "invoke_overhead_ms": delta("T1", "T2"),
        "stream_open_ms": delta("T2", "T3"),
        "provider_first_event_ms": delta("T2", "T4"),
        "provider_text_ttft_ms": delta("T2", "T5"),
        "event_to_text_ms": delta("T4", "T5"),
        "adapter_buffer_ms": delta("T5", "T6"),
        "livekit_text_ttft_ms": delta("T2", "T6"),
        "consumer_buffer_ms": delta("T6", "T7"),
        "consumer_ttft_ms": delta("T0", "T7"),
    }


def schedule(warmups, runs):
    rng = random.Random(42)
    return [
        (i, warm, name)
        for i in range(warmups + runs)
        for warm in (i < warmups,)
        for name in rng.sample(VARIANTS, len(VARIANTS))
    ]


class ObservedStream:
    def __init__(self, stream, recorder):
        self.stream, self.recorder = stream, recorder

    def __getattr__(self, name):
        return getattr(self.stream, name)

    async def __aenter__(self):
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stream.__aexit__(*args)

    def __aiter__(self):
        return self

    async def __anext__(self):
        chunk = await self.stream.__anext__()
        now = time.perf_counter_ns()
        self.recorder["ns"].setdefault("T4", now)
        text = event_kind(chunk) == "text"
        if text:
            self.recorder["ns"].setdefault("T5", now)
        if chunk.usage:
            self.recorder["usage"] = usage_values(chunk.usage)
        if getattr(chunk, "service_tier", None):
            self.recorder["returned_tier"] = chunk.service_tier
        if self.recorder.get("trace") and len(self.recorder["events"]) < 20:
            self.recorder["events"].append(
                {
                    "ms_from_invoke": (now - self.recorder["ns"]["T2"]) / 1e6,
                    "type": "chat.completion.chunk",
                    "text": bool(text),
                    "choices": len(chunk.choices),
                }
            )
        return chunk


class ObservedCompletions:
    def __init__(self, actual, owner):
        self.actual, self.owner = actual, owner

    async def create(self, **kwargs):
        rec = self.owner.current
        rec["snapshot"] = normalize(
            kwargs, model=self.owner.model, timeout=self.owner.timeout, max_retries=0
        )
        rec["ns"]["T2"] = time.perf_counter_ns()
        stream = await self.actual.create(**kwargs)
        rec["ns"]["T3"] = time.perf_counter_ns()
        return ObservedStream(stream, rec)


class ObservedClient:
    def __init__(self, actual, model):
        self.actual, self.model, self.timeout = actual, model, actual.timeout
        self.current = None
        self.chat = type("Chat", (), {})()
        self.chat.completions = ObservedCompletions(actual.chat.completions, self)

    def __getattr__(self, name):
        return getattr(self.actual, name)


async def run_one(
    name,
    client,
    livekit_llm,
    prompt,
    standalone_prompt,
    model,
    tier,
    namespace,
    index,
    warmup,
):
    rec = {
        "ns": {"T0": time.perf_counter_ns()},
        "events": [],
        "trace": index < 3,
        "usage": None,
    }
    client.current = rec
    try:
        if name == "LIVEKIT_LLM_DIRECT":
            from livekit.agents import APIConnectOptions, llm

            ctx = llm.ChatContext()
            ctx.add_message(
                role="system", content="[cache namespace " + namespace + "]\n" + prompt
            )
            ctx.add_message(role="user", content=TRANSCRIPT)
            rec["ns"]["T1"] = time.perf_counter_ns()
            stream = livekit_llm.chat(
                chat_ctx=ctx,
                tools=[],
                conn_options=APIConnectOptions(timeout=60, max_retry=0),
            )
            async with stream:
                async for chunk in stream:
                    if chunk.usage:
                        rec["livekit_usage"] = usage_values(chunk.usage)
                    if chunk.delta and chunk.delta.content:
                        rec["ns"].setdefault("T6", time.perf_counter_ns())
                        rec["ns"].setdefault("T7", time.perf_counter_ns())
        else:
            is_standalone = name == "STANDALONE_EXISTING"
            rec["ns"]["T1"] = (
                None  # existing request builds context inside the SDK call
            )
            row, _ = await request(
                client,
                model,
                standalone_prompt if is_standalone else prompt,
                "warm",
                namespace,
                name,
                index + 1,
                warmup,
                128 if is_standalone else 512,
                None,
                USER_TEXT if is_standalone else TRANSCRIPT,
                service_tier=tier,
                on_text_delta=lambda _text, ns, recorder=rec: recorder["ns"].setdefault(
                    "T7", ns
                ),
            )
            if row["status"] != "ok":
                raise RuntimeError(row["error"]["type"])
            rec["ns"]["T6"] = None
        result = {
            "variant": name,
            "run_index": index + 1,
            "warmup": warmup,
            "status": "ok",
            "requested_tier": tier,
            "tool_count": 0,
            "history_count": 0,
            "timing_ns": rec["ns"],
            "events": rec["events"],
            **stages(rec["ns"]),
            **(rec["usage"] or usage_values(None)),
        }
        result["returned_tier"] = rec.get("returned_tier") or result["returned_tier"]
        if rec.get("snapshot"):
            result["request_sha256"] = hashlib.sha256(
                json.dumps(rec["snapshot"], sort_keys=True, default=str).encode()
            ).hexdigest()
        return result, rec.get("snapshot")
    except Exception as exc:  # noqa: BLE001 - provider failures are benchmark data
        return {
            "variant": name,
            "run_index": index + 1,
            "warmup": warmup,
            "status": "error",
            "error": {"type": type(exc).__name__, "message": str(exc)[:200]},
        }, rec.get("snapshot")


async def cap_ab(client, model, prompt, tier, out, *, runs=10, warmups=2):
    """Change only the output cap with the cascade prompt and transcript."""
    rows = []
    for index in range(runs + warmups):
        for cap in (128, 512) if index % 2 == 0 else (512, 128):
            rec = {
                "ns": {"T0": time.perf_counter_ns()},
                "events": [],
                "trace": False,
                "usage": None,
            }
            client.current = rec
            row, _ = await request(
                client,
                model,
                prompt,
                "warm",
                "benchmark:isolation",
                f"cap_{cap}",
                index + 1,
                index < warmups,
                cap,
                None,
                TRANSCRIPT,
                service_tier=tier,
                on_text_delta=lambda _text, ns, recorder=rec: recorder["ns"].setdefault(
                    "T7", ns
                ),
            )
            result = {
                "variant": f"cap_{cap}",
                "run_index": index + 1,
                "warmup": index < warmups,
                "status": row["status"],
                "requested_tier": tier,
                "tool_count": 0,
                "history_count": 0,
                **stages(rec["ns"]),
                **(rec["usage"] or usage_values(None)),
            }
            result["returned_tier"] = (
                rec.get("returned_tier") or result["returned_tier"]
            )
            if row["status"] != "ok":
                result["error"] = row.get("error")
            rows.append(result)
            append(out, "cap_ab_raw.jsonl", result)
            print(
                "cap A/B",
                index + 1,
                cap,
                result["status"],
                result["consumer_ttft_ms"],
                flush=True,
            )
    (out / "cap_ab_summary.json").write_text(
        json.dumps(
            {
                name: summarize(
                    [dict(row, scenario=name) for row in rows if row["variant"] == name]
                )
                for name in ("cap_128", "cap_512")
            },
            indent=2,
        )
        + "\n"
    )
    return rows


async def user_ab(client, model, prompt, tier, out, *, runs=10, warmups=2):
    """Change only the user text with the cascade prompt and 512-token cap."""
    rows = []
    for index in range(runs + warmups):
        for name, user_text in (
            (("standalone_user", USER_TEXT), ("cascade_user", TRANSCRIPT))
            if index % 2 == 0
            else (("cascade_user", TRANSCRIPT), ("standalone_user", USER_TEXT))
        ):
            rec = {
                "ns": {"T0": time.perf_counter_ns()},
                "events": [],
                "trace": False,
                "usage": None,
            }
            client.current = rec
            row, _ = await request(
                client,
                model,
                prompt,
                "warm",
                "benchmark:isolation",
                name,
                index + 1,
                index < warmups,
                512,
                None,
                user_text,
                service_tier=tier,
                on_text_delta=lambda _text, ns, recorder=rec: recorder["ns"].setdefault(
                    "T7", ns
                ),
            )
            result = {
                "variant": name,
                "run_index": index + 1,
                "warmup": index < warmups,
                "status": row["status"],
                "requested_tier": tier,
                "tool_count": 0,
                "history_count": 0,
                **stages(rec["ns"]),
                **(rec["usage"] or usage_values(None)),
            }
            result["returned_tier"] = (
                rec.get("returned_tier") or result["returned_tier"]
            )
            if row["status"] != "ok":
                result["error"] = row.get("error")
            rows.append(result)
            append(out, "user_ab_raw.jsonl", result)
            print(
                "user A/B",
                index + 1,
                name,
                result["status"],
                result["consumer_ttft_ms"],
                flush=True,
            )
    (out / "user_ab_summary.json").write_text(
        json.dumps(
            {
                name: summarize(
                    [dict(row, scenario=name) for row in rows if row["variant"] == name]
                )
                for name in ("standalone_user", "cascade_user")
            },
            indent=2,
        )
        + "\n"
    )
    return rows


async def reasoning_ab(client, model, prompt, tier, out, *, runs=10, warmups=2):
    """Compare omitted provider default with explicit no reasoning."""
    rows = []
    for index in range(runs + warmups):
        for name, effort in (
            (("reasoning_omitted", None), ("reasoning_none", "none"))
            if index % 2 == 0
            else (("reasoning_none", "none"), ("reasoning_omitted", None))
        ):
            rec = {
                "ns": {"T0": time.perf_counter_ns()},
                "events": [],
                "trace": False,
                "usage": None,
            }
            client.current = rec
            row, _ = await request(
                client,
                model,
                prompt,
                "warm",
                "benchmark:isolation",
                name,
                index + 1,
                index < warmups,
                512,
                None,
                TRANSCRIPT,
                service_tier=tier,
                reasoning_effort=effort,
                on_text_delta=lambda _text, ns, recorder=rec: recorder["ns"].setdefault(
                    "T7", ns
                ),
            )
            result = {
                "variant": name,
                "run_index": index + 1,
                "warmup": index < warmups,
                "status": row["status"],
                "requested_tier": tier,
                "requested_reasoning_effort": effort or "omitted",
                "tool_count": 0,
                "history_count": 0,
                **stages(rec["ns"]),
                **(rec["usage"] or usage_values(None)),
            }
            result["returned_tier"] = (
                rec.get("returned_tier") or result["returned_tier"]
            )
            if row["status"] != "ok":
                result["error"] = row.get("error")
            rows.append(result)
            append(out, "reasoning_ab_raw.jsonl", result)
            print(
                "reasoning A/B",
                index + 1,
                name,
                result["status"],
                result["consumer_ttft_ms"],
                flush=True,
            )
            if index == 0 and row["status"] == "error" and effort == "none":
                (out / "reasoning_ab_unsupported.json").write_text(
                    json.dumps(result["error"]) + "\n"
                )
                return rows
    (out / "reasoning_ab_summary.json").write_text(
        json.dumps(
            {
                name: summarize(
                    [dict(row, scenario=name) for row in rows if row["variant"] == name]
                )
                for name in ("reasoning_omitted", "reasoning_none")
            },
            indent=2,
        )
        + "\n"
    )
    return rows


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--service-tier", default="fast")
    parser.add_argument("--cap-ab-only", action="store_true")
    parser.add_argument("--user-ab-only", action="store_true")
    parser.add_argument("--reasoning-ab-only", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    config = load_env()
    key, model = required(config, "OPENAI_API_KEY", "OPENAI_LLM_MODEL")
    from livekit.plugins import openai as lk_openai
    from openai import AsyncOpenAI

    actual = AsyncOpenAI(api_key=key, max_retries=0, timeout=60)
    client = ObservedClient(actual, model)
    livekit_llm = lk_openai.LLM(
        model=model,
        client=client,
        prompt_cache_key="benchmark:isolation",
        max_completion_tokens=512,
        service_tier=args.service_tier,
    )
    prompt = (ROOT / "llm/prompts/production.txt").read_text()
    standalone_prompt = (ROOT / "llm.production.local.txt").read_text()
    out = args.output_dir or ROOT / "results" / datetime.now(UTC).strftime(
        "%Y-%m-%dT%H%M%SZ"
    )
    out.mkdir(
        parents=True,
        exist_ok=args.cap_ab_only or args.user_ab_only or args.reasoning_ab_only,
    )
    if args.cap_ab_only:
        await cap_ab(client, model, prompt, args.service_tier, out)
        await actual.close()
        print(out)
        return
    if args.user_ab_only:
        await user_ab(client, model, prompt, args.service_tier, out)
        await actual.close()
        print(out)
        return
    if args.reasoning_ab_only:
        await reasoning_ab(client, model, prompt, args.service_tier, out)
        await actual.close()
        print(out)
        return
    benchmark_manifest = manifest(
        "llm_path_isolation",
        "openai",
        model,
        model,
        "provider_routed",
        args.runs,
        args.warmups,
        {
            "service_tier": args.service_tier,
            "sequence_seed": 42,
            "transcript_source": "2026-09-24 cascade artifact",
            "api_path": "chat.completions",
        },
    )
    benchmark_manifest["sdk_versions"]["livekit-plugins-openai"] = (
        importlib.metadata.version("livekit-plugins-openai")
    )
    (out / "manifest.json").write_text(json.dumps(benchmark_manifest, indent=2) + "\n")
    (out / "raw.jsonl").touch()
    (out / "errors.jsonl").touch()
    rows, snapshots = [], {}
    for index, warmup, name in schedule(args.warmups, args.runs):
        namespace = "benchmark:isolation"
        row, snapshot = await run_one(
            name,
            client,
            livekit_llm,
            prompt,
            standalone_prompt,
            model,
            args.service_tier,
            namespace,
            index,
            warmup,
        )
        rows.append(row)
        append(out, "raw.jsonl", row)
        if row["status"] == "error":
            append(out, "errors.jsonl", row)
        if snapshot:
            snapshots[name] = snapshot
        print(index + 1, name, row["status"], row.get("consumer_ttft_ms"), flush=True)
    finish(out, [dict(row, scenario=row["variant"]) for row in rows])
    (out / "request_snapshots.json").write_text(
        json.dumps(snapshots, indent=2, ensure_ascii=False, default=str) + "\n"
    )
    if "STANDALONE_EXISTING" in snapshots and "CASCADE_LLM_EXISTING" in snapshots:
        diff = diff_requests(
            snapshots["STANDALONE_EXISTING"], snapshots["CASCADE_LLM_EXISTING"]
        )
        (out / "llm_request_diff.json").write_text(
            json.dumps(diff, indent=2, ensure_ascii=False) + "\n"
        )
        (out / "llm_request_diff.md").write_text(
            "# Existing request diff\n\n| Field | Status | Standalone | Cascade |\n|---|---|---|---|\n"
            + "".join(
                f"| {key} | {value['status']} | `{str(value['standalone'])[:100]}` | `{str(value['cascade'])[:100]}` |\n"
                for key, value in diff.items()
            )
        )
    await actual.close()
    print(out)


if __name__ == "__main__":
    asyncio.run(main())
