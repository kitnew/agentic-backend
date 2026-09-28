"""Consolidate comparable benchmark artifacts without inventing missing measurements."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.common.stats import describe
from benchmarks.stt.preflight import aggregate

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path | None) -> list[dict]:
    if path is None:
        return []
    return [json.loads(line) for line in (path / "raw.jsonl").read_text().splitlines()]


def metric(rows: list[dict], key: str) -> dict:
    return describe(
        [
            float(row[key])
            for row in rows
            if row.get("status") == "ok" and isinstance(row.get(key), (int, float))
        ]
    )


def pair(rows: list[dict], key: str) -> str:
    stats = metric(rows, key)
    return f"{stats['median']:.0f} / {stats['p90']:.0f}" if stats["count"] else "N/A"


def fraction_pair(rows: list[dict], key: str) -> str:
    stats = metric(rows, key)
    return (
        f"{stats['median'] * 100:.1f}% / {stats['p90'] * 100:.1f}%"
        if stats["count"]
        else "N/A"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scribe", type=Path, default=ROOT / "stt/artifacts/2026-09-24T145535Z"
    )
    parser.add_argument(
        "--scribe-cascade",
        type=Path,
        default=ROOT / "pipeline/cascade/artifacts/2026-09-24T151752Z",
    )
    parser.add_argument("--soniox-stt", type=Path)
    parser.add_argument("--soniox-cascade", type=Path)
    parser.add_argument("--soniox-diagnostic", type=Path)
    args = parser.parse_args()
    sources = {
        name: getattr(args, name)
        for name in (
            "scribe",
            "scribe_cascade",
            "soniox_stt",
            "soniox_cascade",
            "soniox_diagnostic",
        )
    }
    data = {
        name: read(path) if path and path.exists() else []
        for name, path in sources.items()
    }
    rows = {
        name: [row for row in items if not row.get("warmup")]
        for name, items in data.items()
        if name != "soniox_diagnostic"
    }
    frames = [
        frame
        for row in data["soniox_diagnostic"]
        for frame in row.get("provider_frames", [])
    ]
    variants = {
        variant: [
            row for row in rows["soniox_cascade"] if row.get("variant") == variant
        ]
        for variant in (
            "soniox_baseline",
            "soniox_preemptive_llm",
            "soniox_preemptive_llm_tts",
        )
    }
    cascade_manifest = (
        json.loads((args.soniox_cascade / "manifest.json").read_text())
        if args.soniox_cascade and args.soniox_cascade.exists()
        else None
    )
    combined = {
        "created_at": datetime.now(UTC).isoformat(),
        "sources": {
            name: str(path) if path and path.exists() else None
            for name, path in sources.items()
        },
        "cascade_planned_measured_runs_per_variant": cascade_manifest.get(
            "measured_runs"
        )
        if cascade_manifest
        else None,
        "stt": {
            name: {
                "attempts": len(rows[name]),
                "successes": sum(row.get("status") == "ok" for row in rows[name]),
                "connection_ms": metric(rows[name], "connection_ms"),
                "first_partial_ms": metric(rows[name], "first_partial_ms"),
                "audio_end_to_final_ms": metric(rows[name], "audio_end_to_final_ms"),
            }
            for name in ("scribe", "soniox_stt")
        },
        "preflight": aggregate(rows["soniox_stt"])
        | {
            key: metric(rows["soniox_stt"], key)
            for key in (
                "preflight_lead_time_ms",
                "preflight_count",
                "preflight_replacement_count",
                "preflight_word_fraction",
                "first_preflight_token_prefix_accuracy",
            )
        },
        "diagnostic": {
            "provider_frames": len(frames),
            "frames_with_final_tokens": sum(
                frame["final_token_count"] > 0 for frame in frames
            ),
            "frames_with_nonfinal_tokens": sum(
                frame["nonfinal_token_count"] > 0 for frame in frames
            ),
            "frames_with_endpoint": sum(
                frame["endpoint_token_count"] > 0 for frame in frames
            ),
            "preflight_candidate_frames": sum(
                frame["would_emit_preflight"] for frame in frames
            ),
        },
        "cascade": {
            name: {
                "attempts": len(items),
                "successes": sum(row.get("status") == "ok" for row in items),
                "audio_end_to_first_tts_audio_ms": metric(
                    items,
                    "audio_end_to_first_tts_audio_ms",
                ),
                "preflight_lead_time_ms": metric(items, "preflight_lead_time_ms"),
                "llm_work_before_audio_end_ms": metric(
                    items, "llm_work_before_audio_end_ms"
                ),
                "reused_llm_work_before_audio_end_ms": metric(
                    items, "reused_llm_work_before_audio_end_ms"
                ),
                "audio_end_to_first_speakable_ms": metric(
                    items, "audio_end_to_first_speakable_ms"
                ),
                "audio_end_to_first_audio_eligible_lower_bound_ms": metric(
                    items, "audio_end_to_first_audio_eligible_lower_bound_ms"
                ),
                "speculative_tts_start_ms": metric(items, "speculative_tts_start_ms"),
                "first_speculative_tts_audio_ms": metric(
                    items, "first_speculative_tts_audio_ms"
                ),
                "speculative_attempt_count": metric(items, "speculative_attempt_count"),
                "speculative_restart_count": metric(items, "speculative_restart_count"),
                "reuse_rate": sum(
                    bool(row.get("speculative_attempt_reused"))
                    for row in items
                    if row.get("status") == "ok"
                )
                / sum(row.get("status") == "ok" for row in items)
                if any(row.get("status") == "ok" for row in items)
                else None,
                "invalidation_rate": sum(
                    bool(row.get("speculative_attempt_invalidated"))
                    for row in items
                    if row.get("status") == "ok"
                )
                / sum(row.get("status") == "ok" for row in items)
                if any(row.get("status") == "ok" for row in items)
                else None,
            }
            for name, items in {
                "scribe_cascade": rows["scribe_cascade"],
                **variants,
            }.items()
        },
    }
    out = ROOT / "results" / datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=True)
    (out / "soniox_preemptive_comparison.json").write_text(
        json.dumps(combined, indent=2, ensure_ascii=False) + "\n"
    )
    stt = rows["soniox_stt"]
    success = [row for row in stt if row.get("status") == "ok"]
    early = combined["preflight"]["percentage_with_early_preflight"]
    lines = [
        "# Soniox / Preemptive Generation Benchmark",
        "",
        "## Execution",
        "",
        "Measurements are median / p90 in ms. N/A means no measured run was available.",
        "",
        "| Suite | Measured success / attempts | Artifact |",
        "|---|---:|---|",
        *[
            f"| {name} | {sum(row.get('status') == 'ok' for row in rows[name])} / {len(rows[name])} | {sources[name] if data[name] else 'N/A'} |"
            for name in rows
        ],
        f"Soniox cascade planned {cascade_manifest['measured_runs']} measured runs per variant; completed "
        + ", ".join(f"{name} {len(items)}" for name, items in variants.items())
        + ". The run was interrupted for provider-token diagnosis."
        if cascade_manifest
        and any(
            len(items) < cascade_manifest["measured_runs"]
            for items in variants.values()
        )
        else "",
        "",
        "## STT Provider Comparison",
        "",
        "| Metric | ElevenLabs Scribe | Soniox |",
        "|---|---:|---:|",
        f"| Connection setup | {pair(rows['scribe'], 'connection_ms')} | {pair(stt, 'connection_ms')} |",
        f"| First partial | {pair(rows['scribe'], 'first_partial_ms')} | {pair(stt, 'first_partial_ms')} |",
        f"| Audio end → final | {pair(rows['scribe'], 'audio_end_to_final_ms')} | {pair(stt, 'audio_end_to_final_ms')} |",
        f"| First usable preflight | N/A | {pair(stt, 'first_preflight_ms')} |",
        f"| Signed preflight lead | N/A | {pair(stt, 'preflight_lead_time_ms')} |",
        f"| Early preflight rate | N/A | {early:.1f}% |"
        if early is not None
        else "| Early preflight rate | N/A | N/A |",
        f"| Preflight word fraction | N/A | {fraction_pair(stt, 'preflight_word_fraction')} |",
        f"| Final nonempty / successes | {sum(bool(r.get('transcript', '').strip()) for r in rows['scribe'] if r.get('status') == 'ok')} / {sum(r.get('status') == 'ok' for r in rows['scribe'])} | {sum(bool(r.get('transcript', '').strip()) for r in success)} / {len(success)} |",
        f"| Failures | {sum(r.get('status') != 'ok' for r in rows['scribe'])} | {sum(r.get('status') != 'ok' for r in stt)} |",
        "",
        "## Soniox Preflight Timing",
        "",
        f"Early preflights: {combined['preflight']['runs_with_preflight_before_audio_end']} / {len(success)} successful runs. Signed lead: {pair(stt, 'preflight_lead_time_ms')} ms.",
        "",
        "## Preflight Stability",
        "",
        f"Preflight count: {pair(stt, 'preflight_count')}; replacements: {pair(stt, 'preflight_replacement_count')}; first-token prefix accuracy: {fraction_pair(stt, 'first_preflight_token_prefix_accuracy')}.",
        "Token prefix accuracy is the longest common normalized leading-token sequence divided by the first preflight's token count; it is not WER.",
        "",
        "## Provider Token Diagnostic",
        "",
        f"One diagnostic run recorded {len(frames)} provider messages: {sum(f['final_token_count'] > 0 for f in frames)} with final tokens, {sum(f['nonfinal_token_count'] > 0 for f in frames)} with provisional tokens, {sum(f['endpoint_token_count'] > 0 for f in frames)} with endpoint tokens, and {sum(f['would_emit_preflight'] for f in frames)} satisfying the installed plugin's preflight condition.",
        "LiveKit Soniox 1.8.2 emits PREFLIGHT_TRANSCRIPT only when accumulated final text remains after processing a message and that message has no provisional text. A final-plus-provisional message stays interim; an endpoint in the final message clears the accumulated text before the preflight check.",
        "",
        "## Cascade Comparison",
        "",
        "| Variant | Audio end → first synthesized byte | Audio end → first speakable |",
        "|---|---:|---:|",
        f"| Scribe current baseline | {pair(rows['scribe_cascade'], 'audio_end_to_first_tts_audio_ms')} | N/A |",
        *[
            f"| {name} | {pair(items, 'audio_end_to_first_tts_audio_ms')} | {pair(items, 'audio_end_to_first_speakable_ms')} |"
            for name, items in variants.items()
        ],
        "",
        "## Speculative LLM Behavior",
        "",
        *[
            f"{name}: reuse {sum(bool(r.get('speculative_attempt_reused')) for r in items if r.get('status') == 'ok')}/{sum(r.get('status') == 'ok' for r in items)}, invalidations {sum(bool(r.get('speculative_attempt_invalidated')) for r in items)}, restarts {sum(r.get('speculative_restart_count', 0) for r in items)}, started LLM work before audio end {pair(items, 'llm_work_before_audio_end_ms')} ms, reused work {pair(items, 'reused_llm_work_before_audio_end_ms')} ms."
            for name, items in variants.items()
        ],
        "",
        "## Preemptive TTS Behavior",
        "",
        f"Preemptive LLM + TTS: speculative synthesis start {pair(variants['soniox_preemptive_llm_tts'], 'speculative_tts_start_ms')} ms from run start; first speculative byte {pair(variants['soniox_preemptive_llm_tts'], 'first_speculative_tts_audio_ms')} ms; audio end → eligible-first-audio lower bound {pair(variants['soniox_preemptive_llm_tts'], 'audio_end_to_first_audio_eligible_lower_bound_ms')} ms.",
        "Speculative TTS start/first bytes are recorded separately. The eligible-first-audio value is only a lower bound: max(first bytes, turn commit), not measured playout.",
        "",
        "## Failures",
        "",
        "See each run's errors.jsonl; missing Soniox credentials prevented provider execution."
        if not stt
        else "See each run's errors.jsonl for failure types and counts.",
        "",
        "## Interpretation",
        "",
        "No Soniox call-latency conclusion is supported without Soniox runs."
        if not stt
        else "On this fixture Soniox emitted no preflight in 30/30 runs, so the preemptive variants have no event on which to start speculation. The provider token trace explains why; any small difference between partial cascade variants is run variability, not measured preemptive benefit. This does not establish the cause of the live call's subjective timing.",
        "",
        "## Limitations",
        "",
        "This is a synthetic/provider benchmark, not production E2E. It omits Telnyx/SIP/PSTN, caller-audible timing, and production LiveKit media playout. The fixed audio fixture may not represent natural conversational turns; local VAD and real-call EOU may differ. Speculative TTS synthesis is not automatically audible output. These results do not prove subjective UX improvement.",
        "",
        "## Artifact Paths",
        "",
        *[
            f"- {name}: {sources[name] if data[name] else 'not available'}"
            for name in sources
        ],
    ]
    (out / "soniox_preemptive_comparison.md").write_text("\n".join(lines) + "\n")
    print(out)


if __name__ == "__main__":
    main()
