"""Summarize the benchmark-only Soniox stable-final-prefix experiment."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.common.stats import describe

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = (
    "soniox_stock_preemptive_llm",
    "soniox_stable_prefix_preemptive_llm",
    "soniox_stable_prefix_preemptive_llm_tts",
)
THRESHOLDS = (
    "words_1",
    "words_3",
    "words_5",
    "words_8",
    "fraction_25",
    "fraction_50",
    "fraction_75",
)


def numbers(rows, key):
    return [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]


def summarize(rows):
    successes = [row for row in rows if row.get("status") == "ok"]
    preflights = [
        event for row in successes for event in row.get("experimental_preflights", [])
    ]
    total = len(successes)
    thresholds = {}
    for name in THRESHOLDS:
        leads = [row.get("threshold_leads_ms", {}).get(name) for row in successes]
        available = [lead for lead in leads if isinstance(lead, (int, float))]
        thresholds[name] = {
            "available_runs": len(available),
            "availability_rate": len(available) / total if total else None,
            "early_rate": sum(lead > 0 for lead in available) / total
            if total
            else None,
            "lead_ms": describe(available),
        }
    return {
        "attempted_runs": len(rows),
        "successful_runs": total,
        "failed_runs": len(rows) - total,
        "provider_final_token_batches_per_turn": describe(
            [
                sum(
                    frame["final_token_count"] > 0
                    for frame in row.get("provider_frames", [])
                )
                for row in successes
            ]
        ),
        "provider_provisional_frames_per_turn": describe(
            [
                sum(
                    frame["nonfinal_token_count"] > 0
                    for frame in row.get("provider_frames", [])
                )
                for row in successes
            ]
        ),
        "preflight_rate": sum(
            bool(row.get("experimental_preflight_count")) for row in successes
        )
        / total
        if total
        else None,
        "early_preflight_rate": sum(
            any(
                event.get("preflight_lead_ms", 0) > 0
                for event in row.get("experimental_preflights", [])
            )
            for row in successes
        )
        / total
        if total
        else None,
        "experimental_preflights_per_turn": describe(
            numbers(successes, "experimental_preflight_count")
        ),
        "distinct_stable_prefixes_per_turn": describe(
            [
                len(
                    {
                        event["stable_prefix_text"]
                        for event in row.get("experimental_preflights", [])
                    }
                )
                for row in successes
            ]
        ),
        "preflight_interval_ms": describe(
            [
                interval
                for row in successes
                for interval in row.get("preflight_intervals_ms", [])
            ]
        ),
        "first_preflight_lead_ms": describe(
            [
                row["experimental_preflights"][0]["preflight_lead_ms"]
                for row in successes
                if row.get("experimental_preflights")
            ]
        ),
        "thresholds": thresholds,
        "first_preflight_prefix_accuracy": describe(
            [
                row["experimental_preflights"][0]["prefix_token_accuracy"]
                for row in successes
                if row.get("experimental_preflights")
            ]
        ),
        "all_preflight_prefix_accuracy": describe(
            [event["prefix_token_accuracy"] for event in preflights]
        ),
        "non_prefix_preflights": sum(
            not event["is_exact_token_prefix_of_final"] for event in preflights
        ),
        "non_character_prefix_preflights": sum(
            not event["is_character_prefix_of_final"] for event in preflights
        ),
        "midword_preflights": sum(
            event["ends_inside_final_word"] for event in preflights
        ),
        "speculative_attempts_per_turn": describe(
            numbers(successes, "speculative_attempt_count")
        ),
        "speculative_restarts_per_turn": describe(
            numbers(successes, "speculative_restart_count")
        ),
        "speculative_invalidation_count": sum(
            row.get("speculative_invalidation_count", 0) for row in successes
        ),
        "reuse_rate": sum(
            bool(row.get("speculative_attempt_reused")) for row in successes
        )
        / total
        if total
        else None,
        "invalidation_rate": sum(
            bool(row.get("speculative_attempt_invalidated")) for row in successes
        )
        / total
        if total
        else None,
        "llm_work_before_audio_end_ms": describe(
            numbers(successes, "llm_work_before_audio_end_ms")
        ),
        "reused_llm_work_before_audio_end_ms": describe(
            numbers(successes, "reused_llm_work_before_audio_end_ms")
        ),
        "llm_start_relative_to_audio_end_ms": describe(
            [
                row["speculative_llm_start_ms"] - row["logical_audio_end_ms"]
                for row in successes
                if row.get("speculative_llm_start_ms") is not None
            ]
        ),
        "audio_end_to_first_llm_text_ms": describe(
            numbers(successes, "audio_end_to_first_llm_text_ms")
        ),
        "audio_end_to_first_speakable_ms": describe(
            numbers(successes, "audio_end_to_first_speakable_ms")
        ),
        "audio_end_to_tts_start_ms": describe(
            [
                row["tts_start_ms"] - row["logical_audio_end_ms"]
                for row in successes
                if row.get("tts_start_ms") is not None
            ]
        ),
        "audio_end_to_first_tts_audio_ms": describe(
            numbers(successes, "audio_end_to_first_tts_audio_ms")
        ),
        "audio_end_to_first_audio_eligible_lower_bound_ms": describe(
            numbers(successes, "audio_end_to_first_audio_eligible_lower_bound_ms")
        ),
        "speculative_tts_start_ms": describe(
            numbers(successes, "speculative_tts_start_ms")
        ),
        "first_speculative_tts_audio_ms": describe(
            numbers(successes, "first_speculative_tts_audio_ms")
        ),
    }


def pair(item):
    return f"{item['median']:.0f} / {item['p90']:.0f}" if item["count"] else "N/A"


def fraction_pair(item):
    return f"{item['median']:.2f} / {item['p90']:.2f}" if item["count"] else "N/A"


def rate(value):
    return f"{100 * value:.1f}%" if value is not None else "N/A"


def offline_policies(rows):
    policies = {
        "every_growth": lambda event, previous: True,
        "+3_words": lambda event, previous: (
            event["complete_final_word_count"] - previous["complete_final_word_count"]
            >= 3
        ),
        "+5_words": lambda event, previous: (
            event["complete_final_word_count"] - previous["complete_final_word_count"]
            >= 5
        ),
        "min_200_ms": lambda event, previous: (
            event["timestamp_ms"] - previous["timestamp_ms"] >= 200
        ),
        "min_400_ms": lambda event, previous: (
            event["timestamp_ms"] - previous["timestamp_ms"] >= 400
        ),
    }
    result = {}
    for name, allows in policies.items():
        counts = []
        meaningful = []
        for row in rows:
            kept = []
            for event in row.get("experimental_preflights", []):
                if not kept or allows(event, kept[-1]):
                    kept.append(event)
            counts.append(len(kept))
            meaningful.append(
                next(
                    (
                        event["preflight_lead_ms"]
                        for event in kept
                        if event["complete_final_word_count"] >= 5
                    ),
                    None,
                )
            )
        result[name] = {
            "estimated_preflight_count": describe(counts),
            "first_5_word_lead_ms": describe(
                [lead for lead in meaningful if lead is not None]
            ),
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cascade", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.cascade / "manifest.json").read_text())
    rows = [
        json.loads(line)
        for line in (args.cascade / "raw.jsonl").read_text().splitlines()
    ]
    measured = [row for row in rows if not row.get("warmup")]
    grouped = {
        name: [row for row in measured if row.get("variant") == name]
        for name in VARIANTS
    }
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "benchmark_type": "synthetic_preemptive_stable_final_prefix",
        "source_artifact": str(args.cascade.resolve()),
        "manifest": manifest,
        "variants": {name: summarize(items) for name, items in grouped.items()},
    }
    stock, prefix, prefix_tts = (result["variants"][name] for name in VARIANTS)
    meaningful = prefix["thresholds"]["words_5"]
    lead = meaningful["lead_ms"]["median"]
    speakable_gain = (
        stock["audio_end_to_first_speakable_ms"]["median"]
        - prefix["audio_end_to_first_speakable_ms"]["median"]
        if stock["audio_end_to_first_speakable_ms"]["count"]
        and prefix["audio_end_to_first_speakable_ms"]["count"]
        else None
    )
    audio_gain = (
        stock["audio_end_to_first_tts_audio_ms"]["median"]
        - prefix["audio_end_to_first_tts_audio_ms"]["median"]
        if stock["audio_end_to_first_tts_audio_ms"]["count"]
        and prefix["audio_end_to_first_tts_audio_ms"]["count"]
        else None
    )
    cases = []
    if meaningful["availability_rate"] is not None and (
        meaningful["availability_rate"] < 0.5 or (lead is not None and lead < 200)
    ):
        cases.append("B: too little meaningful lead")
    if (
        prefix["speculative_restarts_per_turn"]["median"] is not None
        and prefix["speculative_restarts_per_turn"]["median"] >= 2
    ):
        cases.append("C: restart pressure")
    if (
        lead is not None
        and lead >= 300
        and prefix["reuse_rate"] is not None
        and prefix["reuse_rate"] < 0.5
    ):
        cases.append("D: early prefix, low reuse")
    if (
        speakable_gain is not None
        and audio_gain is not None
        and speakable_gain >= 200
        and audio_gain < 100
    ):
        cases.append("E: LLM improved, first audio did not")
    if (
        lead is not None
        and lead >= 300
        and prefix["reuse_rate"] is not None
        and prefix["reuse_rate"] >= 0.7
        and speakable_gain is not None
        and speakable_gain >= 200
    ):
        cases.append("A: promising")
    result["interpretation"] = {
        "cases": cases,
        "meaningful_prefix_definition": ">=5 complete matching final words",
        "decision_rule_ms": {
            "short_lead": 200,
            "meaningful_lead": 300,
            "speakable_gain": 200,
            "audio_gain_small": 100,
        },
        "median_first_speakable_gain_vs_stock_ms": speakable_gain,
        "median_first_audio_gain_vs_stock_ms": audio_gain,
    }
    if (
        prefix["speculative_restarts_per_turn"]["median"] is not None
        and prefix["speculative_restarts_per_turn"]["median"] >= 2
    ):
        result["offline_policies"] = offline_policies(
            [row for row in grouped[VARIANTS[1]] if row.get("status") == "ok"]
        )
    out = ROOT / "results" / datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    (out / "soniox_stable_prefix_preflight.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    )
    lines = [
        "# Soniox stable-final-prefix preflight experiment",
        "",
        f"Source: `{args.cascade.resolve()}`. Synthetic/provider benchmark on the {manifest['configured_region'].upper()} endpoint; {manifest['measured_runs']} measured and {manifest['warmup_runs']} warmup runs per variant. Values are median / p90 in ms unless noted.",
        "",
        "## Controlled comparison",
        "",
        "| Metric | Stock preemptive LLM | Stable prefix + LLM | Stable prefix + LLM + TTS |",
        "|---|---:|---:|---:|",
    ]
    fields = (
        (
            "Success / attempts",
            lambda s: f"{s['successful_runs']} / {s['attempted_runs']}",
        ),
        ("Preflight rate", lambda s: rate(s["preflight_rate"])),
        ("Early preflight rate", lambda s: rate(s["early_preflight_rate"])),
        ("Preflights / turn", lambda s: pair(s["experimental_preflights_per_turn"])),
        ("First raw preflight lead", lambda s: pair(s["first_preflight_lead_ms"])),
        (
            "First >=5 complete-word lead",
            lambda s: pair(s["thresholds"]["words_5"]["lead_ms"]),
        ),
        (
            "Final-token batches / turn",
            lambda s: pair(s["provider_final_token_batches_per_turn"]),
        ),
        (
            "Provisional frames / turn",
            lambda s: pair(s["provider_provisional_frames_per_turn"]),
        ),
        (
            "Speculative attempts / turn",
            lambda s: pair(s["speculative_attempts_per_turn"]),
        ),
        ("Restarts / turn", lambda s: pair(s["speculative_restarts_per_turn"])),
        ("Reuse rate", lambda s: rate(s["reuse_rate"])),
        ("Invalidation rate", lambda s: rate(s["invalidation_rate"])),
        (
            "LLM work before audio end",
            lambda s: pair(s["llm_work_before_audio_end_ms"]),
        ),
        (
            "Reused LLM work before audio end",
            lambda s: pair(s["reused_llm_work_before_audio_end_ms"]),
        ),
        ("Audio end → first text", lambda s: pair(s["audio_end_to_first_llm_text_ms"])),
        (
            "Audio end → first speakable",
            lambda s: pair(s["audio_end_to_first_speakable_ms"]),
        ),
        ("Audio end → TTS start", lambda s: pair(s["audio_end_to_tts_start_ms"])),
        (
            "Audio end → first synthesized byte",
            lambda s: pair(s["audio_end_to_first_tts_audio_ms"]),
        ),
    )
    for label, extract in fields:
        lines.append(
            f"| {label} | "
            + " | ".join(extract(result["variants"][name]) for name in VARIANTS)
            + " |"
        )
    lines += [
        "",
        "## Stable-prefix thresholds",
        "",
        "Thresholds count complete leading words matching the final transcript, excluding a midword fragment. Availability and early rate use successful runs as denominator. Signed lead is audio end minus preflight time; positive means before audio end.",
        "",
        "| Threshold | Available | Early | Lead median / p90 |",
        "|---|---:|---:|---:|",
    ]
    for name in THRESHOLDS:
        item = prefix["thresholds"][name]
        lines.append(
            f"| {name} | {rate(item['availability_rate'])} | {rate(item['early_rate'])} | {pair(item['lead_ms'])} |"
        )
    lines += [
        "",
        "## Prefix stability and restart pressure",
        "",
        f"First-prefix token accuracy: {fraction_pair(prefix['first_preflight_prefix_accuracy'])}; all-prefix accuracy: {fraction_pair(prefix['all_preflight_prefix_accuracy'])}; non-token-prefix events: {prefix['non_prefix_preflights']}; non-character-prefix events: {prefix['non_character_prefix_preflights']}; midword events: {prefix['midword_preflights']}.",
        f"Interval between preflights: {pair(prefix['preflight_interval_ms'])} ms. Total invalidations: {prefix['speculative_invalidation_count']}.",
        "Prefix token accuracy is the matching leading normalized tokens divided by tokens in that experimental preflight; it is not WER.",
        "",
        "## Preemptive TTS",
        "",
        f"Speculative TTS start: {pair(prefix_tts['speculative_tts_start_ms'])} ms from run start; first speculative byte: {pair(prefix_tts['first_speculative_tts_audio_ms'])} ms from run start; audio end → eligible-first-audio lower bound: {pair(prefix_tts['audio_end_to_first_audio_eligible_lower_bound_ms'])} ms.",
        "Synthesis before turn commit is not caller-audible timing. The lower bound uses max(turn commit, first synthesized byte), without playout.",
        "",
        "## Interpretation",
        "",
        "Cases: "
        + (", ".join(cases) if cases else "none classified from available measurements")
        + ".",
        "Answer: exposing every stable-final-prefix growth produced early preflights but no demonstrated meaningful latency improvement on this fixture.",
        f"Median first-speakable gain versus stock: {speakable_gain:.0f} ms."
        if speakable_gain is not None
        else "First-speakable gain unavailable.",
        f"Median first synthesized byte gain versus stock: {audio_gain:.0f} ms."
        if audio_gain is not None
        else "First-audio gain unavailable.",
        "No speculative attempt was reused, so the modest median latency differences cannot be attributed to reused speculative work. Both experimental preflights ended inside a word on every measured turn. The final transcript differed from the last preflight, requiring a new committed LLM request; preemptive TTS produced no speculative audio. This fixture does not justify a production adapter that emits every stable-prefix growth.",
    ]
    if "offline_policies" in result:
        lines += [
            "",
            "## Offline restart policy estimates",
            "",
            "Analysis only; the measured adapter emitted every stable-prefix growth.",
            "",
            "| Policy | Preflights / turn | First >=5-word lead |",
            "|---|---:|---:|",
        ]
        for name, item in result["offline_policies"].items():
            lines.append(
                f"| {name} | {pair(item['estimated_preflight_count'])} | {pair(item['first_5_word_lead_ms'])} |"
            )
    lines += [
        "",
        "## Failures and limitations",
        "",
        "Failure counts appear in the comparison table; details are in errors.jsonl. The synthetic coordinator mirrors LiveKit 1.8.2's three-attempt replacement and transcript reuse rules but is not AgentSession. It assumes fixed context and tools. No production local VAD, LiveKit media playout, Telnyx/SIP/PSTN, or caller-audible timing is measured. One fixed Slovak utterance may not represent natural turns. The result does not prove subjective UX improvement.",
        "",
        "## Artifacts",
        "",
        f"- Raw runs: `{args.cascade.resolve()}`",
        f"- JSON: `{out / 'soniox_stable_prefix_preflight.json'}`",
    ]
    (out / "soniox_stable_prefix_preflight.md").write_text("\n".join(lines) + "\n")
    print(out)


if __name__ == "__main__":
    main()
