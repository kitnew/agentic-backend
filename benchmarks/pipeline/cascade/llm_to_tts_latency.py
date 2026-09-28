"""Measure the installed LiveKit OpenAI → ElevenLabs streaming path."""

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import aiohttp
from common.config import load_env, required
from common.stats import describe
from livekit.agents import APIConnectOptions, llm, tokenize
from livekit.plugins import elevenlabs
from livekit.plugins import openai as livekit_openai
from llm.path_isolation import ObservedClient
from llm.run import safe_error
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[2]
TRANSCRIPT = (
    "Dobrý deň, chcel by som si rezervovať dvojložkovú izbu od dvadsiateho "
    "piateho do dvadsiateho šiesteho septembra."
)
STAGES = {
    "provider_to_livekit_ms": ("provider_text", "livekit_text"),
    "livekit_to_tts_receive_ms": ("livekit_text", "tts_receive"),
    "tts_receive_to_plugin_ms": ("tts_receive", "plugin_receive"),
    "plugin_to_tokenizer_receive_ms": ("plugin_receive", "tokenizer_receive"),
    "livekit_to_tokenizer_ms": ("livekit_text", "tokenizer_emit"),
    "tokenizer_receive_to_emit_ms": ("tokenizer_receive", "tokenizer_emit"),
    "tokenizer_to_tts_receive_ms": ("tokenizer_emit", "tts_receive"),
    "tokenizer_to_websocket_ms": ("tokenizer_emit", "websocket_send"),
    "tts_receive_to_websocket_ms": ("tts_receive", "websocket_send"),
    "websocket_to_provider_audio_ms": ("websocket_send", "provider_audio"),
    "provider_to_livekit_audio_ms": ("provider_audio", "livekit_audio"),
    "llm_text_to_audio_ms": ("livekit_text", "livekit_audio"),
}


def mark(rec, key, ns=None):
    rec["ns"].setdefault(key, time.perf_counter_ns() if ns is None else ns)


def stages(ns):
    result = {
        name: (ns[end] - ns[start]) / 1e6
        if ns.get(start) is not None and ns.get(end) is not None
        else None
        for name, (start, end) in STAGES.items()
    }
    result["tokenizer_to_tts_receive_ms"] = None
    return result


def redact_error(exc):
    return safe_error(exc)


class ObservedTokenStream:
    def __init__(self, actual, owner):
        self.actual, self.owner = actual, owner

    def push_text(self, text):
        rec = self.owner.rec
        if rec is not None:
            now = time.perf_counter_ns()
            mark(rec, "tokenizer_receive", now)
            rec["tokenizer_input"].append(
                {"ns": now, "text": text, "buffer_before": self.actual._in_buf}
            )
        self.actual.push_text(text)

    def flush(self):
        if self.owner.rec is not None:
            mark(self.owner.rec, "tokenizer_flush")
        self.actual.flush()

    def end_input(self):
        if self.owner.rec is not None:
            mark(self.owner.rec, "tokenizer_end")
        self.actual.end_input()

    async def aclose(self):
        await self.actual.aclose()

    def __aiter__(self):
        return self

    async def __anext__(self):
        token = await self.actual.__anext__()
        rec = self.owner.rec
        if rec is not None:
            now = time.perf_counter_ns()
            mark(rec, "tokenizer_emit", now)
            rec["tokenizer_output"].append({"ns": now, "text": token.token})
        return token


class ObservedSentenceTokenizer(tokenize.blingfire.SentenceTokenizer):
    def __init__(self, min_sentence_len):
        super().__init__(min_sentence_len=min_sentence_len)
        self.rec = None

    def stream(self, *, language=None):
        return ObservedTokenStream(super().stream(language=language), self)


class ImmediateTokenStream:
    """Benchmark-only tokenizer bypass: emit the supplied complete phrase."""

    def __init__(self):
        self.queue = asyncio.Queue()

    def push_text(self, text):
        self.queue.put_nowait(tokenize.TokenData(token=text, segment_id="bypass"))

    def flush(self):
        pass

    def end_input(self):
        self.queue.put_nowait(None)

    async def aclose(self):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


class ImmediateTokenizer(tokenize.SentenceTokenizer):
    def tokenize(self, text, *, language=None):
        return [text]

    def stream(self, *, language=None):
        return ImmediateTokenStream()


class ObservedWebSocket:
    def __init__(self, actual, owner):
        self.actual, self.owner = actual, owner

    def __getattr__(self, name):
        return getattr(self.actual, name)

    async def send_json(self, payload, *args, **kwargs):
        rec = self.owner.rec
        if (
            rec is not None
            and payload.get("inputs")
            and payload["inputs"][0].get("text")
        ):
            mark(rec, "websocket_send")
            rec["websocket_text"].append(
                {
                    "ns": time.perf_counter_ns(),
                    "text": payload["inputs"][0]["text"],
                    "flush": payload.get("flush", False),
                }
            )
        return await self.actual.send_json(payload, *args, **kwargs)

    async def receive(self, *args, **kwargs):
        message = await self.actual.receive(*args, **kwargs)
        rec = self.owner.rec
        if rec is not None and message.type == aiohttp.WSMsgType.TEXT:
            try:
                payload = json.loads(message.data)
            except ValueError:
                payload = {}
            if payload.get("audio"):
                mark(rec, "provider_audio")
        return message


class ObservedSession:
    def __init__(self, actual):
        self.actual, self.rec = actual, None

    def __getattr__(self, name):
        return getattr(self.actual, name)

    async def ws_connect(self, *args, **kwargs):
        return ObservedWebSocket(await self.actual.ws_connect(*args, **kwargs), self)


async def replay(events, push):
    if not events:
        return
    started = time.perf_counter_ns()
    first = events[0]["relative_ms"]
    for event in events:
        await asyncio.sleep(
            max(
                0,
                (event["relative_ms"] - first) / 1000
                - (time.perf_counter_ns() - started) / 1e9,
            )
        )
        push(event["text"])


async def one_run(
    kind, model, prompt, client, sdk, tts, tokenizer, session, transcript, captured=None
):
    rec = {
        "kind": kind,
        "status": "ok",
        "ns": {},
        "cadence": [],
        "tokenizer_input": [],
        "tokenizer_output": [],
        "websocket_text": [],
    }
    tokenizer.rec = session.rec = rec
    sdk.current = {"ns": {}, "events": [], "trace": False, "usage": None}
    text_queue = asyncio.Queue()

    async def input_text():
        while (item := await text_queue.get()) is not None:
            mark(rec, "tts_receive")
            yield item

    async def consume_tts():
        async with tts.stream() as stream:

            async def forward():
                async for text in input_text():
                    mark(rec, "plugin_receive")
                    stream.push_text(text)
                stream.end_input()

            task = asyncio.create_task(forward())
            try:
                async for audio in stream:
                    mark(rec, "livekit_audio")
            finally:
                await task

    async def produce_live():
        ctx = llm.ChatContext()
        ctx.add_message(role="system", content=prompt)
        ctx.add_message(role="user", content=transcript)
        mark(rec, "request_invoke")
        stream = client.chat(
            chat_ctx=ctx,
            tools=[],
            conn_options=APIConnectOptions(timeout=60, max_retry=0),
        )
        cumulative = ""
        async with stream:
            async for chunk in stream:
                content = chunk.delta.content if chunk.delta else None
                if not content:
                    continue
                now = time.perf_counter_ns()
                mark(rec, "livekit_text", now)
                cumulative += content
                rec["cadence"].append(
                    {
                        "ns": now,
                        "text": content,
                        "cumulative_chars": len(cumulative),
                        "cumulative_words": len(cumulative.split()),
                    }
                )
                text_queue.put_nowait(content)
        rec["llm_completion_ns"] = time.perf_counter_ns()

    async def produce_replay():
        await replay(captured["cadence"], text_queue.put_nowait)

    async def produce_bypass():
        text_queue.put_nowait(captured["tokenizer_output"][0]["text"])

    try:
        task = asyncio.create_task(consume_tts())
        try:
            if kind == "CURRENT":
                await produce_live()
            elif kind == "PRE_RECORDED_LLM_STREAM":
                await produce_replay()
            else:
                await produce_bypass()
        finally:
            text_queue.put_nowait(None)
        await task
    except Exception as exc:  # noqa: BLE001 - provider failures are benchmark data
        rec["status"] = "error"
        rec["error"] = redact_error(exc)
    finally:
        tokenizer.rec = session.rec = None

    provider = sdk.current["ns"].get("T5") if kind == "CURRENT" else None
    if provider is not None:
        rec["ns"]["provider_text"] = provider
    rec.update(stages(rec["ns"]))
    origin = rec["ns"].get("livekit_text") or rec["ns"].get("tts_receive")
    for event in (
        rec["cadence"]
        + rec["tokenizer_input"]
        + rec["tokenizer_output"]
        + rec["websocket_text"]
    ):
        event["relative_ms"] = (event.pop("ns") - origin) / 1e6 if origin else None
    rec["timestamps_ms"] = {
        key: (value - origin) / 1e6 if origin else None
        for key, value in rec.pop("ns").items()
    }
    cumulative = ""
    for event in rec["cadence"]:
        cumulative += event["text"]
        if "first_complete_word_ms" not in rec and re.search(r"\S+\s", cumulative):
            rec["first_complete_word_ms"] = event["relative_ms"]
        if "first_punctuation_ms" not in rec and re.search(r"[.!?…]", cumulative):
            rec["first_punctuation_ms"] = event["relative_ms"]
        if "first_comma_ms" not in rec and "," in cumulative:
            rec["first_comma_ms"] = event["relative_ms"]
    for name, start in (
        ("first_complete_word_to_tokenizer_ms", "first_complete_word_ms"),
        ("first_punctuation_to_tokenizer_ms", "first_punctuation_ms"),
    ):
        rec[name] = (
            rec["timestamps_ms"]["tokenizer_emit"] - rec[start]
            if start in rec and "tokenizer_emit" in rec["timestamps_ms"]
            else None
        )
    rec["first_tokenizer_reason"] = (
        "stream_close_or_flush"
        if rec["timestamps_ms"].get("tokenizer_end") is not None
        and rec["timestamps_ms"].get("tokenizer_emit") is not None
        and rec["timestamps_ms"]["tokenizer_end"]
        <= rec["timestamps_ms"]["tokenizer_emit"]
        else "next_sentence_candidate"
        if rec["tokenizer_output"]
        else None
    )
    return rec


def report(rows, config, result_dir):
    measured = [
        r
        for r in rows
        if r["kind"] == "CURRENT" and not r["warmup"] and r["status"] == "ok"
    ]
    table = []
    for name in STAGES:
        stats = describe([r[name] for r in measured if r.get(name) is not None])
        total = describe(
            [
                r["llm_text_to_audio_ms"]
                for r in measured
                if r.get("llm_text_to_audio_ms") is not None
            ]
        )["median"]
        pct = (
            100 * stats["median"] / total
            if stats["median"] is not None and total
            else None
        )
        table.append(
            {
                "stage": name,
                "median_ms": stats["median"],
                "p90_ms": stats["p90"],
                "n": stats["count"],
                "percent_of_total": pct,
            }
        )
    total_median = describe([r["llm_text_to_audio_ms"] for r in measured])["median"]
    first = (
        min(measured, key=lambda r: abs(r["llm_text_to_audio_ms"] - total_median))
        if measured
        else None
    )
    summary = {
        "configuration": config,
        "successful_runs": len(measured),
        "table": table,
        "example": first,
        "variants": {
            name: [r for r in rows if r["kind"] == name]
            for name in ("PRE_RECORDED_LLM_STREAM", "BYPASS_TOKENIZER")
        },
    }
    (result_dir / "llm_to_tts_latency.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    lines = [
        "# LLM to TTS latency",
        "",
        f"Current measured runs: {len(measured)}",
        "",
        "| Stage | Median ms | P90 ms | N | % total |",
        "|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {r['stage']} | {r['median_ms']} | {r['p90_ms']} | {r['n']} | {r['percent_of_total']} |"
        for r in table
    ]
    if first:
        lines += [
            "",
            "## Example first turn",
            "",
            f"First tokenizer output: {first['tokenizer_output'][0]['text'] if first['tokenizer_output'] else 'unavailable'}",
            "",
            "| ms from first LiveKit text | Event | Text |",
            "|---:|---|---|",
        ]
        for ev in first["cadence"]:
            if ev["relative_ms"] <= 2000:
                lines.append(
                    f"| {ev['relative_ms']:.1f} | LLM delta; {ev['cumulative_chars']} chars; {ev['cumulative_words']} words | {ev['text']!r} |"
                )
        for key, label in (
            ("tokenizer_emit", "tokenizer emits"),
            ("websocket_send", "websocket sends"),
            ("provider_audio", "provider audio"),
            ("livekit_audio", "LiveKit audio"),
        ):
            if key in first["timestamps_ms"]:
                lines.append(f"| {first['timestamps_ms'][key]:.1f} | {label} | |")
    (result_dir / "llm_to_tts_latency.md").write_text("\n".join(lines) + "\n")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--min-sentence-chars", type=int, default=20)
    parser.add_argument("--transcript", default=TRANSCRIPT)
    args = parser.parse_args()
    config = load_env()
    llm_key, model, tts_key, tts_model, voice = required(
        config,
        "OPENAI_API_KEY",
        "OPENAI_LLM_MODEL",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_TTS_MODEL",
        "ELEVENLABS_VOICE_ID",
    )
    prompt = (ROOT / "llm/prompts/production.txt").read_text()
    result_dir = ROOT / "results" / datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    result_dir.mkdir()
    settings = {
        "model": model,
        "reasoning_effort": "none",
        "requested_service_tier": "fast",
        "tts_model": tts_model,
        "voice_id": voice,
        "auto_mode": False,
        "min_sentence_chars": args.min_sentence_chars,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "transcript": args.transcript,
        "production_runtime_value_verified": False,
    }
    sdk = ObservedClient(AsyncOpenAI(api_key=llm_key, max_retries=0, timeout=60), model)
    client = livekit_openai.LLM(
        model=model,
        client=sdk,
        reasoning_effort="none",
        service_tier="fast",
        max_completion_tokens=512,
        prompt_cache_key="benchmark:"
        + hashlib.sha256(prompt.encode()).hexdigest()[:32],
    )
    tokenizer = ObservedSentenceTokenizer(args.min_sentence_chars)
    async with aiohttp.ClientSession() as http:
        session = ObservedSession(http)
        tts = elevenlabs.TTS(
            api_key=tts_key,
            model=tts_model,
            voice_id=voice,
            language="sk",
            auto_mode=False,
            word_tokenizer=tokenizer,
            http_session=session,
        )
        rows = []
        for i in range(args.runs + args.warmups):
            row = await one_run(
                "CURRENT",
                model,
                prompt,
                client,
                sdk,
                tts,
                tokenizer,
                session,
                args.transcript,
            )
            row.update(run_index=i + 1, warmup=i < args.warmups)
            rows.append(row)
            with (result_dir / "raw.jsonl").open("a") as file:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                f"{i + 1}/{args.runs + args.warmups}: {row['status']} first_text_to_audio={row.get('llm_text_to_audio_ms')}",
                flush=True,
            )
        captured = next(
            (
                r
                for r in rows
                if r["status"] == "ok" and r["cadence"] and r["tokenizer_output"]
            ),
            None,
        )
        if captured:
            for kind in ("PRE_RECORDED_LLM_STREAM", "BYPASS_TOKENIZER"):
                active_tts = tts
                if kind == "BYPASS_TOKENIZER":
                    active_tts = elevenlabs.TTS(
                        api_key=tts_key,
                        model=tts_model,
                        voice_id=voice,
                        language="sk",
                        auto_mode=False,
                        word_tokenizer=ImmediateTokenizer(),
                        http_session=session,
                    )
                    await (
                        active_tts._current_connection()
                    )  # warm connection for the bypass
                row = await one_run(
                    kind,
                    model,
                    prompt,
                    client,
                    sdk,
                    active_tts,
                    tokenizer,
                    session,
                    args.transcript,
                    captured,
                )
                row.update(run_index=1, warmup=False)
                rows.append(row)
                with (result_dir / "raw.jsonl").open("a") as file:
                    file.write(json.dumps(row, ensure_ascii=False) + "\n")
                if active_tts is not tts:
                    await active_tts.aclose()
        await tts.aclose()
    await client.aclose()
    report(rows, settings, result_dir)
    print(result_dir)


if __name__ == "__main__":
    asyncio.run(main())
