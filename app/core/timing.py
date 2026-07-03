from datetime import datetime, timezone
from time import perf_counter
from typing import Any


def start_timer() -> float:
    return perf_counter()


def elapsed_seconds(started_at: float) -> float:
    return round(perf_counter() - started_at, 6)


def new_timing_trace() -> dict[str, Any]:
    return {
        "unit": "seconds",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "components": {},
    }


def record_component_timing(
    timing_trace: dict[str, Any],
    component: str,
    started_at: float,
    **metadata,
) -> None:
    component_timing = {"seconds": elapsed_seconds(started_at)}
    component_timing.update(
        {key: value for key, value in metadata.items() if value is not None}
    )
    timing_trace.setdefault("components", {})[component] = component_timing


def finish_timing_trace(timing_trace: dict[str, Any], started_at: float) -> dict[str, Any]:
    timing_trace["total_seconds"] = elapsed_seconds(started_at)
    timing_trace["finished_at"] = datetime.now(timezone.utc).isoformat()
    return timing_trace
