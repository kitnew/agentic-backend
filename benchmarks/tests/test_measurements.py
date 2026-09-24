import importlib.util
from pathlib import Path

import pytest

from benchmarks.common.stats import describe, summarize


def script(path):
    spec = importlib.util.spec_from_file_location(
        path.replace("/", "_"), Path("benchmarks") / path / "run.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stats_excludes_warmup_and_failures():
    rows = [
        {"warmup": True, "status": "ok", "total_ms": 1000},
        {"warmup": False, "status": "ok", "total_ms": 10},
        {"warmup": False, "status": "ok", "total_ms": 20},
        {"warmup": False, "status": "error", "total_ms": 100},
    ]
    result = summarize(rows)
    assert (
        result["successful_runs"],
        result["failed_runs"],
        result["failure_rate"],
    ) == (2, 1, 1 / 3)
    assert result["metrics"]["total_ms"]["p95"] == 19.5
    assert describe([10])["stddev_sample"] is None


def test_cache_state_needs_provider_usage():
    cache = script("llm").cache_state
    assert cache(None, "warm") == "unavailable"
    assert cache(0, "warm") == "warm_intended_miss"
    assert cache(1024, "cold") == "confirmed_hit"


def test_realtime_boundaries():
    derive = script("realtime").derive
    result = derive(
        [
            {"event": "last_input_audio_sent", "elapsed_ms": 10},
            {"event": "response.created", "elapsed_ms": 30},
            {"event": "response.output_audio.delta", "elapsed_ms": 50},
            {"event": "response.done", "elapsed_ms": 90},
        ]
    )
    assert result["input_end_to_first_audio_ms"] == 40
    assert result["input_end_to_completion_ms"] == 80
    assert result["session_init_ms"] is None


def test_artifacts_keep_raw_and_group_summary_without_credentials(tmp_path):
    from benchmarks.common.artifacts import append, create, finish

    script_path = tmp_path / "llm" / "run.py"
    script_path.parent.mkdir()
    script_path.touch()
    path = create(
        str(script_path),
        {"benchmark_type": "llm", "provider": "azure_openai", "model": "example"},
    )
    rows = [
        {"scenario": "minimal_cold", "status": "ok", "warmup": False, "total_ms": 5.5},
        {
            "scenario": "minimal_warm",
            "status": "error",
            "warmup": False,
            "total_ms": 8.0,
        },
    ]
    for row in rows:
        append(path, "raw.jsonl", row)
    result = finish(path, rows)
    assert result["groups"]["minimal_cold"]["metrics"]["total_ms"]["count"] == 1
    assert len((path / "raw.jsonl").read_text().splitlines()) == 2
    assert "SECRET_KEY" not in "".join(
        p.read_text() for p in path.iterdir() if p.is_file()
    )


@pytest.mark.asyncio
async def test_llm_stream_measures_first_text_before_completion():
    from types import SimpleNamespace as N

    from benchmarks.llm.run import request

    class Stream:
        async def __aiter__(self):
            yield N(
                id="one",
                choices=[N(delta=N(content="Dobrý "))],
                usage=None,
                service_tier="priority",
            )
            yield N(
                id="two",
                choices=[N(delta=N(content="deň."))],
                usage=N(
                    prompt_tokens=1200,
                    completion_tokens=3,
                    prompt_tokens_details=N(cached_tokens=1024),
                ),
                service_tier="priority",
            )

    class Completions:
        async def create(self, **kwargs):
            assert kwargs["stream"] is True
            assert kwargs["messages"][1]["content"] == "test"
            assert kwargs["service_tier"] == "fast"
            return Stream()

    client = N(chat=N(completions=Completions()))
    row, events = await request(
        client,
        "deployment",
        "instruction",
        "warm",
        "abc",
        "minimal_warm",
        1,
        False,
        64,
        None,
        "test",
        "fast",
    )
    assert row["status"] == "ok"
    assert row["cache_state"] == "confirmed_hit"
    assert row["response_service_tier"] == "priority"
    assert row["first_text_ms"] <= row["first_speakable_ms"] <= row["total_ms"]
    assert row["output_text"] == "Dobrý deň."
    assert len(events) == 2


def test_realtime_ws_url_matches_installed_azure_routes():
    from benchmarks.realtime.run import ws_url

    assert ws_url("https://example.openai.azure.com/openai/v1", "demo", None) == (
        "wss://example.openai.azure.com/openai/v1/realtime?model=demo"
    )
    assert ws_url("https://example.openai.azure.com", "demo", "2025-01-01") == (
        "wss://example.openai.azure.com/openai/realtime?deployment=demo&api-version=2025-01-01"
    )
    assert ws_url(
        "wss://example.openai.azure.com/openai/v1", "demo", "YOUR_API_VERSION"
    ) == ("wss://example.openai.azure.com/openai/v1/realtime?model=demo")
    with pytest.raises(ValueError):
        ws_url("ws://example.openai.azure.com/openai/v1", "demo", None)


def test_realtime_handshake_error_keeps_status_without_key():
    from types import SimpleNamespace as N

    from benchmarks.realtime.run import safe_error

    class InvalidStatus(Exception):
        response = N(
            status_code=400, reason_phrase="Bad Request", body=b"bad key=secret"
        )

    error = safe_error(InvalidStatus("handshake failed"), "secret")
    assert error["status_code"] == 400
    assert error["body"] == "bad key=[redacted]"


@pytest.mark.asyncio
async def test_realtime_continued_turn_keeps_session_and_history():
    import json
    import time

    from benchmarks.realtime.run import trial

    class Socket:
        def __init__(self):
            self.sent = []
            self.events = [
                {"type": "session.created"},
                {"type": "session.updated"},
                {"type": "response.output_audio.delta", "delta": "AAAA"},
                {"type": "response.done", "response": {"status": "completed"}},
                {"type": "response.output_audio.delta", "delta": "AAAA"},
                {"type": "response.done", "response": {"status": "completed"}},
            ]

        async def send(self, payload):
            self.sent.append(json.loads(payload))

        async def recv(self):
            return json.dumps(self.events.pop(0))

    ws = Socket()
    first, _ = await trial(ws, b"\0\0", "prompt", time.perf_counter_ns(), 1)
    second, _ = await trial(
        ws, b"\0\0", "prompt", time.perf_counter_ns(), 1, configure_session=False
    )
    assert first["status"] == second["status"] == "ok"
    assert [event["type"] for event in ws.sent].count("session.update") == 1
    assert [event["type"] for event in ws.sent].count("response.create") == 2


@pytest.mark.asyncio
async def test_realtime_main_reuses_only_continued_session(monkeypatch, tmp_path):
    import json
    import sys
    import types
    import wave

    from benchmarks.realtime import run

    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 2400)

    sockets = []

    class Socket:
        def __init__(self):
            self.sent = []
            self.events = [{"type": "session.created"}]
            sockets.append(self)

        async def send(self, payload):
            event = json.loads(payload)
            self.sent.append(event)
            if event["type"] == "session.update":
                self.events.append({"type": "session.updated"})
            if event["type"] == "response.create":
                self.events.extend(
                    [
                        {"type": "response.output_audio.delta", "delta": "AAAA"},
                        {"type": "response.done", "response": {"status": "completed"}},
                    ]
                )

        async def recv(self):
            return json.dumps(self.events.pop(0))

        async def close(self):
            pass

    async def connect(*args, **kwargs):
        assert args[0].startswith("wss://")
        return Socket()

    monkeypatch.setitem(
        sys.modules, "websockets", types.SimpleNamespace(connect=connect)
    )
    monkeypatch.setattr(
        run,
        "load_env",
        lambda: {
            "AZURE_REALTIME_ENDPOINT": "wss://example.openai.azure.com/openai/v1",
            "AZURE_REALTIME_API_KEY": "key",
            "AZURE_REALTIME_DEPLOYMENT": "model",
        },
    )
    monkeypatch.setattr(run, "create", lambda *args: tmp_path)
    monkeypatch.setattr(run, "manifest", lambda *args: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--audio",
            str(audio),
            "--runs",
            "2",
            "--warmups",
            "0",
            "--prompts",
            "minimal",
        ],
    )
    await run.main()

    rows = [
        json.loads(line) for line in (tmp_path / "raw.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 4 and all(row["status"] == "ok" for row in rows)
    assert len(sockets) == 3
    assert sorted(
        [len([e for e in ws.sent if e["type"] == "response.create"]) for ws in sockets]
    ) == [1, 1, 2]


@pytest.mark.asyncio
async def test_llm_main_interleaves_scenarios_and_passes_tier(monkeypatch, tmp_path):
    import sys

    from benchmarks.llm import run

    calls = []

    async def fake_request(*args, **kwargs):
        calls.append((args[5], args[6], args[4], kwargs["service_tier"]))
        return {
            "scenario": args[5],
            "run_index": args[6],
            "warmup": args[7],
            "status": "ok",
            "ttft_ms": 1,
            "total_ms": 2,
            "cached_input_tokens": 0,
        }, []

    monkeypatch.setattr(
        run,
        "load_env",
        lambda: {
            "OPENAI_API_KEY": "key",
            "OPENAI_LLM_MODEL": "gpt-5.6-terra",
        },
    )
    monkeypatch.setattr(run, "request", fake_request)
    monkeypatch.setattr(run, "create", lambda *args: tmp_path)
    monkeypatch.setattr(run, "manifest", lambda *args: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--provider",
            "openai",
            "--service-tier",
            "fast",
            "--prompts",
            "minimal",
            "--runs",
            "2",
            "--warmups",
            "0",
        ],
    )
    await run.main()

    assert len(calls) == 4
    assert all(tier == "fast" for _, _, _, tier in calls)
    assert all(
        {scenario for scenario, index, _, _ in calls if index == i}
        == {"minimal_cold", "minimal_warm"}
        for i in (1, 2)
    )
    assert (
        len(
            {
                namespace
                for scenario, _, namespace, _ in calls
                if scenario == "minimal_warm"
            }
        )
        == 1
    )
    assert (
        len(
            {
                namespace
                for scenario, _, namespace, _ in calls
                if scenario == "minimal_cold"
            }
        )
        == 2
    )
    assert len((tmp_path / "raw.jsonl").read_text().splitlines()) == 4


def test_realtime_legacy_audio_event_is_measured():
    from benchmarks.realtime.run import derive

    result = derive(
        [
            {"event": "last_input_audio_sent", "elapsed_ms": 12.0},
            {"event": "response.audio.delta", "elapsed_ms": 54.0},
        ]
    )
    assert result["input_end_to_first_audio_ms"] == 42.0
