"""Summarize real-call Voice Agent turns without changing their raw records."""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.stats import describe

WATERFALL = {
    "cascade": (
        ("Speech end → STT final", "speech_to_stt_final"),
        ("STT final → EOU", "stt_final_to_eou"),
        ("EOU → LLM start", "eou_to_llm_start"),
        ("LLM → first token", "llm_ttft"),
        ("First token → TTS input", "first_token_to_tts_input"),
        ("TTS input → speakable", "tts_input_to_speakable"),
        ("TTS start → first frame", "tts_ttfb"),
        ("First frame → output proxy", "first_audio_to_output"),
    ),
    "realtime": (
        ("Speech stop → response", "speech_to_response_created"),
        ("Response → first frame", "realtime_response_to_first_audio"),
        ("First frame → output proxy", "realtime_first_audio_to_output"),
    ),
    "half-cascade": (
        ("Speech stop → response", "speech_to_response_created"),
        ("Response → TTS input", "realtime_response_to_tts_input"),
        ("TTS input → speakable", "tts_input_to_speakable"),
        ("TTS → first frame", "tts_ttfb"),
        ("First frame → output proxy", "first_audio_to_output"),
    ),
}


def analyze(records: list[dict]) -> dict:
    groups = defaultdict(list)
    for record in records:
        if record.get("architecture") in WATERFALL:
            groups[record["architecture"]].append(record)
    result = {}
    for architecture, turns in groups.items():
        metrics = {}
        for key in sorted(
            {key for turn in turns for key in turn["latencies_ms"]}
            | {"causal_stage_sum"}
        ):
            metrics[key] = describe(
                [
                    float(value)
                    for turn in turns
                    if isinstance(
                        value := (
                            turn.get("causal_stage_sum_ms")
                            if key == "causal_stage_sum"
                            else turn["latencies_ms"].get(key)
                        ),
                        int | float,
                    )
                ]
            )
        result[architecture] = {"turns": len(turns), "metrics": metrics}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("records", type=Path, help="turns.jsonl or its directory")
    args = parser.parse_args()
    source = args.records / "turns.jsonl" if args.records.is_dir() else args.records
    records = [json.loads(line) for line in source.read_text().splitlines() if line]
    summary = analyze(records)
    destination = source.parent
    (destination / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (destination / "summary.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "architecture",
                "metric",
                "count",
                "min",
                "max",
                "mean",
                "median",
                "p25",
                "p75",
                "p90",
                "p95",
                "stddev_population",
                "coefficient_of_variation",
                "iqr",
            )
        )
        for architecture, group in summary.items():
            for metric, stats in group["metrics"].items():
                writer.writerow(
                    (
                        architecture,
                        metric,
                        *(
                            stats[key]
                            for key in (
                                "count",
                                "min",
                                "max",
                                "mean",
                                "median",
                                "p25",
                                "p75",
                                "p90",
                                "p95",
                                "stddev_population",
                                "coefficient_of_variation",
                                "iqr",
                            )
                        ),
                    )
                )
    for architecture, group in summary.items():
        print(f"\n{architecture.upper()} — {group['turns']} turns")
        print(f"{'Metric':35} {'count':>5} {'median':>10} {'p90':>10}")
        for label, key in WATERFALL[architecture]:
            stats = group["metrics"].get(key)
            if stats and stats["count"]:
                print(
                    f"{label:35} {stats['count']:5} {stats['median']:10.1f} {stats['p90']:10.1f}"
                )
        stats = group["metrics"].get("speech_to_first_audio_output")
        if stats and stats["count"]:
            print(
                f"{'Speech end proxy → output':35} {stats['count']:5} {stats['median']:10.1f} {stats['p90']:10.1f}"
            )


if __name__ == "__main__":
    main()
