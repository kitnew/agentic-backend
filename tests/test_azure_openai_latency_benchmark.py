from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "azure_openai_latency_benchmark.py"
SPEC = spec_from_file_location("azure_openai_latency_benchmark", SCRIPT)
assert SPEC and SPEC.loader
BENCHMARK = module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


def test_percentile_interpolates_and_handles_empty_samples() -> None:
    assert BENCHMARK.percentile([], 95) is None
    assert BENCHMARK.percentile([1, 2, 3, 4], 50) == 2.5
    assert BENCHMARK.percentile([1, 2, 3, 4], 90) == 3.7


def test_summary_groups_provider_model_and_includes_maximum() -> None:
    row = {
        "provider": "openai",
        "requested_model": "gpt-5.6-luna",
        "workload": "warm",
        "requested_service_tier": "default",
        "error": None,
        **{metric: 1 for metric in BENCHMARK.METRICS},
    }

    summary = BENCHMARK.summarize([row])

    stats = summary["openai/gpt-5.6-luna/warm/default"]["first_raw_event_ms"]
    assert stats["p50"] == stats["p90"] == stats["p95"] == stats["p99"] == 1.0
    assert stats["max"] == stats["mean"] == 1.0


def test_frozen_request_shape_reuses_the_first_serialization(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    first = ([{"role": "system", "content": "first"}], [], "cache-key")
    later = ([{"role": "system", "content": "later"}], [], "other-key")

    assert BENCHMARK.frozen_request_shape(path, first) == first
    assert BENCHMARK.frozen_request_shape(path, later) == first


def test_calculator_probe_validates_the_production_schema() -> None:
    row = {
        "tool_calls": [
            {
                "id": "call-1",
                "name": "calculator",
                "arguments": '{"operation":"multiply","operands":["17","23"]}',
            }
        ]
    }

    result = BENCHMARK.calculator_probe_result(row)

    assert result["selected_calculator"] is True
    assert result["strict_schema_valid"] is True
    assert result["expected_operation"] is True
