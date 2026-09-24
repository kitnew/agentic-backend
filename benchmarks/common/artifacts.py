import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from common.stats import summarize


def create(script: str, manifest: dict) -> Path:
    root = Path(script).resolve().parent / "artifacts"
    path = root / datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    suffix = 1
    while path.exists():
        path = root / (datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ") + f"-{suffix}")
        suffix += 1
    path.mkdir(parents=True)
    (path / "raw.jsonl").touch()
    (path / "errors.jsonl").touch()
    (path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    return path


def append(path: Path, filename: str, row: dict) -> None:
    with (path / filename).open("a") as file:
        file.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def finish(path: Path, rows: list[dict]) -> dict:
    summary = summarize(rows)
    group_key = next(
        (
            key
            for key in ("scenario", "text_kind", "target")
            if any(key in row for row in rows)
        ),
        None,
    )
    if group_key:
        groups = sorted({row[group_key] for row in rows if group_key in row})
        summary["groups"] = {
            group: summarize([row for row in rows if row.get(group_key) == group])
            for group in groups
        }
        summary["group_key"] = group_key
    (path / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    )
    with (path / "summary.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        columns = (
            "count",
            "min",
            "max",
            "mean",
            "median",
            "p25",
            "p75",
            "p90",
            "p95",
            "p99",
            "variance_population",
            "stddev_population",
            "stddev_sample",
            "coefficient_of_variation",
            "iqr",
        )
        writer.writerow(("group", "metric", *columns))
        for group, values in [
            ("all", summary),
            *((name, values) for name, values in summary.get("groups", {}).items()),
        ]:
            for metric, stats in values["metrics"].items():
                writer.writerow((group, metric, *(stats[column] for column in columns)))
    print(
        f"success={summary['successful_runs']} failed={summary['failed_runs']} artifacts={path}"
    )
    return summary
