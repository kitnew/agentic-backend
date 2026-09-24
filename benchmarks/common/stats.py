import math
import statistics


def percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def describe(values: list[float]) -> dict:
    if not values:
        return {
            key: None
            for key in (
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
        } | {"count": 0}
    mean = statistics.fmean(values)
    p25, p75 = percentile(values, 25), percentile(values, 75)
    population_std = statistics.pstdev(values)
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": mean,
        "median": statistics.median(values),
        "p25": p25,
        "p75": p75,
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "variance_population": statistics.pvariance(values),
        "stddev_population": population_std,
        "stddev_sample": statistics.stdev(values) if len(values) > 1 else None,
        "coefficient_of_variation": population_std / mean if mean else None,
        "iqr": p75 - p25,
    }


def summarize(rows: list[dict]) -> dict:
    measured = [row for row in rows if not row.get("warmup")]
    successful = [row for row in measured if row.get("status") == "ok"]
    result = {
        "successful_runs": len(successful),
        "failed_runs": len(measured) - len(successful),
        "failure_rate": (len(measured) - len(successful)) / len(measured)
        if measured
        else None,
        "metrics": {},
    }
    keys = {
        key
        for row in successful
        for key, value in row.items()
        if key.endswith("_ms") and isinstance(value, (int, float))
    }
    for key in sorted(keys):
        result["metrics"][key] = describe(
            [
                float(row[key])
                for row in successful
                if isinstance(row.get(key), (int, float))
            ]
        )
    return result
