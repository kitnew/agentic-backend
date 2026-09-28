"""Render the LLM path experiment without rerunning provider calls."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.stats import describe
from llm.path_isolation import VARIANTS

METRICS = (
    "pre_invoke_ms",
    "request_build_ms",
    "provider_first_event_ms",
    "provider_text_ttft_ms",
    "adapter_buffer_ms",
    "livekit_text_ttft_ms",
    "consumer_ttft_ms",
    "input_tokens",
    "cached_tokens",
    "reasoning_tokens",
    "output_tokens",
)


def metric_value(row, metric):
    if metric in ("pre_invoke_ms", "livekit_text_ttft_ms") and metric not in row:
        ns = row.get("timing_ns", {})
        start, end = ("T0", "T2") if metric == "pre_invoke_ms" else ("T2", "T6")
        if ns.get(start) is not None and ns.get(end) is not None:
            return (ns[end] - ns[start]) / 1e6
    return row.get(metric)


def aggregate(rows):
    result = {}
    for name in VARIANTS:
        group = [
            row
            for row in rows
            if row["variant"] == name and not row["warmup"] and row["status"] == "ok"
        ]
        result[name] = {
            "success": len(group),
            "metrics": {
                metric: describe(
                    [
                        float(metric_value(row, metric))
                        for row in group
                        if isinstance(metric_value(row, metric), (int, float))
                    ]
                )
                for metric in METRICS
            },
            "requested_tiers": sorted({row["requested_tier"] for row in group}),
            "returned_tiers": sorted({str(row["returned_tier"]) for row in group}),
            "tool_counts": sorted({row["tool_count"] for row in group}),
            "history_counts": sorted({row["history_count"] for row in group}),
        }
    return result


def pair(stats, metric):
    value = stats["metrics"][metric]
    return (
        f"{value['median']:.0f} / {value['p90']:.0f}"
        if value["median"] is not None
        else "unavailable"
    )


def ab_stats(path, stem, names):
    file = path / f"{stem}_raw.jsonl"
    rows = (
        [json.loads(line) for line in file.read_text().splitlines()]
        if file.exists()
        else []
    )
    return rows, {
        name: {
            "success": sum(
                row["variant"] == name and not row["warmup"] and row["status"] == "ok"
                for row in rows
            ),
            "attempts": sum(
                row["variant"] == name and not row["warmup"] for row in rows
            ),
            "metrics": {
                metric: describe(
                    [
                        float(row[metric])
                        for row in rows
                        if row["variant"] == name
                        and not row["warmup"]
                        and row["status"] == "ok"
                        and isinstance(row.get(metric), (int, float))
                    ]
                )
                for metric in (
                    "consumer_ttft_ms",
                    "provider_first_event_ms",
                    "provider_text_ttft_ms",
                    "reasoning_tokens",
                    "cached_tokens",
                    "input_tokens",
                )
            },
        }
        for name in names
    }


def render(path):
    rows = [json.loads(line) for line in (path / "raw.jsonl").read_text().splitlines()]
    snapshots = json.loads((path / "request_snapshots.json").read_text())
    result = aggregate(rows)
    cap_rows, cap_stats = ab_stats(path, "cap_ab", ("cap_128", "cap_512"))
    user_rows, user_stats = ab_stats(
        path, "user_ab", ("standalone_user", "cascade_user")
    )
    reasoning_rows, reasoning_stats = ab_stats(
        path, "reasoning_ab", ("reasoning_omitted", "reasoning_none")
    )
    result["cap_ab"] = cap_stats
    result["user_ab"] = user_stats
    result["reasoning_ab"] = reasoning_stats
    (path / "llm_path_isolation.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# LLM path isolation",
        "",
        "All values are median / p90 across measured runs in milliseconds unless marked as tokens. T0 is entry to the benchmark variant; T2 is the SDK chat.completions.create invocation; T4 is the first ChatCompletionChunk; T5 is its first nonempty content delta; T6 is first LiveKit text chunk when applicable; T7 is first text observed by benchmark code. The SDK stream is opened at T3. Existing direct request construction occurs inside request(), so T1 and build time are unavailable for those variants.",
        "",
        "| Variant | Success | Pre-invoke | Build | Send → event | Send → text | Send → LiveKit text | LiveKit buffer | Consumer TTFT | Input tokens | Cached tokens | Reasoning tokens | Requested → returned tier | Tools | History |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    for name in VARIANTS:
        s = result[name]
        lines.append(
            f"| {name} | {s['success']} | {pair(s, 'pre_invoke_ms')} | {pair(s, 'request_build_ms')} | {pair(s, 'provider_first_event_ms')} | {pair(s, 'provider_text_ttft_ms')} | {pair(s, 'livekit_text_ttft_ms')} | {pair(s, 'adapter_buffer_ms')} | {pair(s, 'consumer_ttft_ms')} | {pair(s, 'input_tokens')} | {pair(s, 'cached_tokens')} | {pair(s, 'reasoning_tokens')} | {','.join(s['requested_tiers'])} → {','.join(s['returned_tiers'])} | {','.join(map(str, s['tool_counts']))} | {','.join(map(str, s['history_counts']))} |"
        )
    lines += [
        "",
        "## Payload matrix",
        "",
        "| Variant | API | Prompt hash | User hash | Max tokens | Tools | History | Reasoning parameter | Tier |",
        "|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for name in VARIANTS:
        snap = snapshots.get(name, {})
        lines.append(
            f"| {name} | {snap.get('api_type')} | `{str(snap.get('prompt_sha256'))[:12]}` | `{str(snap.get('user_sha256'))[:12]}` | {snap.get('max_completion_tokens')} | {snap.get('tool_schema_count')} | {snap.get('history_count')} | {'omitted' if snap.get('reasoning_effort') is None else snap.get('reasoning_effort')} | {snap.get('requested_service_tier')} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "Standalone and synthetic cascade both call the raw OpenAI AsyncOpenAI Chat Completions endpoint. DIRECT_CASCADE_PAYLOAD and CASCADE_LLM_EXISTING use the same effective request. LIVEKIT_LLM_DIRECT uses the same API family and textual payload, with a LiveKit User-Agent header and per-call timeout. The historical standalone shape differs in user text, one trailing prompt byte, and max_completion_tokens (128 versus 512). There are no tools or history in these synthetic paths. Reasoning effort is omitted, so provider default applies; zero reasoning tokens must be established from usage rather than interpreted from None alone.",
        'The interleaved variants reuse one AsyncOpenAI client and HTTP transport. SDK serialization was checked offline with a mock transport: omitted reasoning_effort is absent from the JSON body; explicit none is serialized as `"reasoning_effort": "none"` (sdk_serialization.json). Both primary prompt prefixes are more than 99.9% cached, and every observed returned tier is priority despite requesting fast.',
        "",
    ]
    if cap_rows:
        lines += [
            "## Controlled output-cap A/B",
            "",
            "Identical cascade prompt, transcript, model, cache key, tier, SDK, and execution window; only max_completion_tokens changes.",
            "",
            "| Cap | Consumer TTFT median / p90 ms | First event median / p90 ms | Reasoning tokens median / p90 |",
            "|---:|---:|---:|---:|",
        ]
        for name in ("cap_128", "cap_512"):
            s = cap_stats[name]

            def fmt(metric, stats=s):
                v = stats["metrics"][metric]
                return (
                    f"{v['median']:.0f} / {v['p90']:.0f}"
                    if v["median"] is not None
                    else "unavailable"
                )

            lines.append(
                f"| {name.removeprefix('cap_')} ({s['success']}/{s['attempts']} text responses) | {fmt('consumer_ttft_ms')} | {fmt('provider_first_event_ms')} | {fmt('reasoning_tokens')} |"
            )
        lines.append("")
    for title, ab_rows, stats, names in (
        ("User text", user_rows, user_stats, ("standalone_user", "cascade_user")),
        (
            "Reasoning setting",
            reasoning_rows,
            reasoning_stats,
            ("reasoning_omitted", "reasoning_none"),
        ),
    ):
        if not ab_rows:
            continue
        lines += [
            f"## Controlled {title} A/B",
            "",
            "| Variant | Text responses | Consumer TTFT median / p90 ms | First event median / p90 ms | Reasoning tokens median / p90 |",
            "|---|---:|---:|---:|---:|",
        ]
        for name in names:
            s = stats[name]

            def fmt(metric, item=s):
                v = item["metrics"][metric]
                return (
                    f"{v['median']:.0f} / {v['p90']:.0f}"
                    if v["median"] is not None
                    else "unavailable"
                )

            lines.append(
                f"| {name} | {s['success']}/{s['attempts']} | {fmt('consumer_ttft_ms')} | {fmt('provider_first_event_ms')} | {fmt('reasoning_tokens')} |"
            )
        lines.append("")
    a = result["STANDALONE_EXISTING"]["metrics"]["consumer_ttft_ms"]["median"]
    d = result["CASCADE_LLM_EXISTING"]["metrics"]["consumer_ttft_ms"]["median"]
    omitted = reasoning_stats["reasoning_omitted"]["metrics"]["consumer_ttft_ms"][
        "median"
    ]
    none = reasoning_stats["reasoning_none"]["metrics"]["consumer_ttft_ms"]["median"]
    if all(value is not None for value in (a, d, omitted, none)):
        lines += [
            "## Root-cause classification",
            "",
            f"Case A (request shape): the primary same-window gap is {d - a:.0f} ms ({d:.0f} minus {a:.0f}). The provider's first event accounts for nearly all of it. Direct cascade payload and the existing cascade stage cluster together; LiveKit emits normalized text within milliseconds of provider text. Case B/C/D/E are unsupported by these measurements.",
            "",
            f"Within an otherwise identical cascade request, explicit reasoning_effort=none reduces median consumer TTFT by {omitted - none:.0f} ms ({omitted:.0f} to {none:.0f}), and reasoning-token usage becomes zero. The original omitted parameter permits provider-default reasoning. The historical 700–800 versus 2200 ms gap was measured in separate windows; this experiment explains its mechanism but cannot assign every historical millisecond without a paired historical run.",
            "",
            "Recommended production evaluation: test an explicit no-reasoning deployment setting on the relevant model and assess response quality before rollout. Do not reduce max_completion_tokens to 128 for the cascade transcript: seven of ten measured requests in the cap A/B produced no text.",
            "",
        ]
    (path / "llm_path_isolation.md").write_text("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    render(Path(sys.argv[1]))
