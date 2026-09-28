from benchmarks.llm.path_isolation import (
    VARIANTS,
    diff_requests,
    event_kind,
    normalize,
    schedule,
    stages,
    usage_values,
)


def test_request_normalization_redacts_content_and_headers():
    request = normalize(
        {
            "model": "example",
            "messages": [
                {"role": "system", "content": "private prompt"},
                {"role": "user", "content": "private user"},
            ],
            "tools": [{"type": "function", "function": {"name": "x"}}],
            "extra_headers": {"Authorization": "Bearer secret"},
            "stream": True,
        },
        model="example",
        timeout=60,
        max_retries=0,
    )
    assert request["prompt_chars"] == len("private prompt")
    assert request["prompt_bytes"] == len(b"private prompt")
    assert request["tool_schema_count"] == 1
    assert request["history_count"] == 0
    assert request["reasoning_effort"] == "omitted"
    assert "private prompt" not in str(request)
    assert "private user" not in str(request)
    assert "Bearer secret" not in str(request)


def test_diff_distinguishes_missing_and_different():
    result = diff_requests(
        {"model": "a", "temperature": None, "top_p": 1},
        {"model": "b", "temperature": 0.5, "top_p": None},
    )
    assert result["model"]["status"] == "different"
    assert result["temperature"]["status"] == "missing in standalone"
    assert result["top_p"]["status"] == "missing in cascade"
    assert result["tools"]["status"] == "same"
    assert result["effective_reasoning_setting"]["status"] == "unobservable"


def test_stages_handle_missing_boundaries():
    result = stages(
        {"T0": 0, "T2": 2_000_000, "T4": 3_000_000, "T5": 4_000_000, "T7": 5_000_000}
    )
    assert result["provider_first_event_ms"] == 1
    assert result["provider_text_ttft_ms"] == 2
    assert result["consumer_ttft_ms"] == 5
    assert result["request_build_ms"] is None
    assert result["adapter_buffer_ms"] is None


def test_usage_extracts_reasoning_cache_and_tier():
    from types import SimpleNamespace as N

    usage = N(
        prompt_tokens=100,
        completion_tokens=20,
        prompt_tokens_details=N(cached_tokens=80),
        completion_tokens_details=N(reasoning_tokens=10),
        service_tier="priority",
    )
    assert usage_values(usage) == {
        "input_tokens": 100,
        "cached_tokens": 80,
        "output_tokens": 20,
        "reasoning_tokens": 10,
        "returned_tier": "priority",
    }
    assert usage_values(None)["reasoning_tokens"] is None


def test_provider_event_classification():
    from types import SimpleNamespace as N

    assert event_kind(N(usage=None, choices=[])) == "non_text"
    assert event_kind(N(usage=None, choices=[N(delta=N(content="hello"))])) == "text"
    assert event_kind(N(usage=N(prompt_tokens=1), choices=[])) == "usage"


def test_schedule_is_interleaved_and_deterministic():
    result = schedule(2, 3)
    assert result == schedule(2, 3)
    assert len(result) == 20
    for index in range(5):
        round_names = [name for i, _, name in result if i == index]
        assert set(round_names) == set(VARIANTS)
    assert sum(warm for _, warm, _ in result) == 8


def test_summary_aggregation_excludes_warmup_and_failure():
    from benchmarks.llm.report_path_isolation import aggregate

    rows = [
        {
            "variant": "STANDALONE_EXISTING",
            "warmup": True,
            "status": "ok",
            "consumer_ttft_ms": 999,
        },
        {
            "variant": "STANDALONE_EXISTING",
            "warmup": False,
            "status": "ok",
            "consumer_ttft_ms": 10,
            "requested_tier": "fast",
            "returned_tier": "priority",
            "tool_count": 0,
            "history_count": 0,
        },
        {
            "variant": "STANDALONE_EXISTING",
            "warmup": False,
            "status": "error",
            "consumer_ttft_ms": 100,
        },
    ]
    result = aggregate(rows)["STANDALONE_EXISTING"]
    assert result["success"] == 1
    assert result["metrics"]["consumer_ttft_ms"]["median"] == 10
