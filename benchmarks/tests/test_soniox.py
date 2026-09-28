import asyncio
import json

import pytest

from benchmarks.stt.preflight import aggregate, metrics
from benchmarks.stt.run import soniox_endpoint


def test_signed_lead_and_preflight_sequence():
    sequence = [
        {"elapsed_ms": 80, "text": "Chcel by som"},
        {"elapsed_ms": 90, "text": "Chcel by som izbu"},
    ]
    result = metrics(sequence, "Chcel by som izbu.", 100)
    assert result["preflight_lead_time_ms"] == 20
    assert result["preflight_before_audio_end"] is True
    assert result["preflight_count"] == 2
    assert result["preflight_replacement_count"] == 1
    assert result["first_preflight_prefix_matches_final"] is True
    assert result["first_preflight_token_prefix_accuracy"] == 1
    assert result["latest_preflight_prefix_matches_final"] is True
    assert (
        metrics([{"elapsed_ms": 120, "text": "Áno"}], "Áno", 100)[
            "preflight_lead_time_ms"
        ]
        == -20
    )
    assert (
        metrics([{"elapsed_ms": 120, "text": "Áno"}], "Áno", 100)[
            "preflight_before_audio_end"
        ]
        is False
    )
    assert (
        metrics([{"elapsed_ms": 80, "text": "Chcel inak"}], "Chcel izbu", 100)[
            "first_preflight_token_prefix_accuracy"
        ]
        == 0.5
    )


def test_aggregate_excludes_warmups_and_failures():
    rows = [
        {
            "warmup": True,
            "status": "ok",
            "preflight_count": 1,
            "preflight_before_audio_end": True,
        },
        {
            "status": "ok",
            "preflight_count": 1,
            "preflight_before_audio_end": True,
            "transcript": "A",
        },
        {
            "status": "ok",
            "preflight_count": 0,
            "preflight_before_audio_end": False,
            "transcript": "B",
        },
        {"status": "error", "preflight_count": 1, "preflight_before_audio_end": True},
    ]
    assert aggregate(rows) == {
        "runs_with_preflight": 1,
        "runs_with_preflight_before_audio_end": 1,
        "percentage_with_early_preflight": 50,
        "final_transcript_non_empty_rate": 1,
    }


@pytest.mark.asyncio
async def test_speculative_replacement_reuse_and_invalidation():
    from benchmarks.pipeline.cascade.soniox import Coordinator

    def launch(text, at_ns):
        gate = asyncio.Event()
        return {
            "text": text,
            "start_ns": at_ns,
            "gate": gate,
            "task": asyncio.create_task(gate.wait()),
        }

    coordinator = Coordinator(launch, True)
    coordinator.preflight("Prvý", 10)
    old = coordinator.current
    coordinator.preflight("Druhý", 20)
    assert old["task"].cancelled() or old["task"].cancelling()
    coordinator.commit("druhý!", 30)
    assert coordinator.reused is True
    assert coordinator.current["gate"].is_set()
    assert (
        len(coordinator.attempts),
        coordinator.invalidations,
        coordinator.restarts,
    ) == (2, 1, 1)
    await asyncio.gather(
        *(item["task"] for item in coordinator.attempts), return_exceptions=True
    )

    mismatch = Coordinator(launch, True)
    mismatch.preflight("Wrong", 10)
    mismatch.commit("Right", 20)
    assert mismatch.current is None and mismatch.invalidations == 1
    await asyncio.gather(
        *(item["task"] for item in mismatch.attempts), return_exceptions=True
    )


def test_eu_endpoint_and_artifacts_redact_key(tmp_path):
    from benchmarks.common.artifacts import append, create, finish

    assert soniox_endpoint("EU") == "wss://stt-rt.eu.soniox.com/transcribe-websocket"
    assert soniox_endpoint("GLOBAL/US") == soniox_endpoint("us")
    script = tmp_path / "run.py"
    script.touch()
    path = create(str(script), {"provider": "soniox", "configured_region": "eu"})
    row = {"status": "ok", "warmup": False, "preflight_lead_time_ms": -5, "error": None}
    append(path, "raw.jsonl", row)
    finish(path, [row])
    assert (
        json.loads((path / "summary.json").read_text())["metrics"][
            "preflight_lead_time_ms"
        ]["median"]
        == -5
    )
    assert "SECRET_SONIOX_KEY" not in "".join(
        p.read_text() for p in path.iterdir() if p.is_file()
    )


@pytest.mark.asyncio
async def test_soniox_error_never_persists_exception_with_key(monkeypatch):
    from livekit.plugins import soniox

    from benchmarks.stt.run import measure_soniox

    def fail(_):
        raise RuntimeError("SECRET_SONIOX_KEY rejected")

    monkeypatch.setattr(soniox.STT, "stream", fail)
    row = await measure_soniox("SECRET_SONIOX_KEY", "eu", b"\0\0", 24000, 1)
    assert row["status"] == "error"
    assert row["error"] == {"type": "RuntimeError"}
    assert "SECRET_SONIOX_KEY" not in json.dumps(row)


@pytest.mark.asyncio
async def test_cascade_preserves_negative_audio_end_relative_timing(monkeypatch):
    from benchmarks.pipeline.cascade import soniox

    async def fake_stt(*args, on_end, **kwargs):
        on_end("Dobrý deň", 1)
        return {
            "status": "ok",
            "transcript": "Dobrý deň",
            "logical_audio_end_ms": 100,
            "first_final_transcript_ms": 5,
            "first_preflight_ms": None,
        }

    async def fake_llm(*args, on_text_delta, **kwargs):
        on_text_delta("Dobrý deň, ako vám môžem pomôcť?", 0)
        return {
            "status": "ok",
            "first_text_ms": 1,
            "requested_service_tier": "fast",
            "response_service_tier": "priority",
        }, []

    async def fake_tts(*args):
        return {"status": "ok", "first_audio_ms": 1}

    monkeypatch.setattr(soniox, "measure_soniox", fake_stt)
    monkeypatch.setattr(soniox, "request", fake_llm)
    monkeypatch.setattr(soniox, "tts_measure", fake_tts)
    row = await soniox.trial(
        b"\0\0",
        24000,
        "key",
        "eu",
        None,
        "model",
        "prompt",
        None,
        "tts-url",
        "key",
        "eleven_v3_conversational",
        "voice",
        1,
        512,
        "soniox_baseline",
    )
    assert row["status"] == "ok"
    assert row["audio_end_to_first_llm_text_ms"] < 0
    assert row["audio_end_to_first_tts_audio_ms"] < 0


@pytest.mark.asyncio
async def test_provider_token_diagnostic_explains_missing_preflight():
    import time
    from types import SimpleNamespace

    import aiohttp

    from benchmarks.stt.diagnose_soniox import ObservedSocket

    class Socket:
        async def __aiter__(self):
            for tokens in (
                [{"text": "A", "is_final": True}, {"text": "B", "is_final": False}],
                [{"text": "B", "is_final": True}, {"text": "<end>", "is_final": True}],
            ):
                yield SimpleNamespace(
                    type=aiohttp.WSMsgType.TEXT, data=json.dumps({"tokens": tokens})
                )

    frames = []
    async for _ in ObservedSocket(Socket(), frames, time.perf_counter_ns()):
        pass
    assert [frame["would_emit_preflight"] for frame in frames] == [False, False]
    assert frames[0]["accumulated_final_char_count"] == 1
    assert frames[0]["provisional_char_count"] == 1
    assert frames[1]["endpoint_token_count"] == 1


def test_stable_final_prefix_adapter_preserves_provisional_tail_and_endpoint(
    monkeypatch,
):
    from types import SimpleNamespace

    from livekit.agents import stt

    from benchmarks.stt import stable_prefix

    emitted = []
    stream = SimpleNamespace(_event_ch=SimpleNamespace(send_nowait=emitted.append))
    ticks = iter((1_000_000_000, 2_000_000_000))
    monkeypatch.setattr(stable_prefix, "perf_counter_ns", lambda: next(ticks))
    adapter = stable_prefix.StableFinalPrefix(stream, 0)
    adapter.observe([{"text": " by som", "is_final": False}], 0)
    assert emitted == []
    adapter.observe(
        [
            {"text": "Chcel", "is_final": True, "api_key": "SECRET"},
            {"text": " by som", "is_final": False},
        ],
        0,
    )
    adapter.observe([{"text": " by som", "is_final": False}], 0)
    adapter.observe(
        [
            {"text": " by som", "is_final": True},
            {"text": " rezervovať", "is_final": False},
        ],
        0,
    )
    adapter.observe(
        [
            {"text": " izbu", "is_final": True},
            {"text": "<end>", "is_final": True},
        ],
        0,
    )
    adapter.observe([{"text": " ignored", "is_final": True}], 0)
    assert [event.type for event in emitted] == [
        stt.SpeechEventType.PREFLIGHT_TRANSCRIPT
    ] * 2
    assert [event.alternatives[0].text for event in emitted] == [
        "Chcel",
        "Chcel by som",
    ]
    assert [event["provisional_tail_text"] for event in adapter.events] == [
        " by som",
        " rezervovať",
    ]
    assert [event["new_final_tokens"] for event in adapter.events] == [
        ["Chcel"],
        [" by som"],
    ]
    assert "SECRET" not in json.dumps(adapter.events)
    adapter.audio_end_ns = 2_500_000_000
    events = adapter.finish("Chcel by som izbu")
    assert [event["preflight_relative_to_audio_end_ms"] for event in events] == [
        -1500,
        -500,
    ]
    assert [event["preflight_lead_ms"] for event in events] == [1500, 500]
    assert all(event["is_exact_token_prefix_of_final"] for event in events)
    assert all(event["prefix_token_accuracy"] == 1 for event in events)


def test_stable_prefix_thresholds_and_non_prefix_accuracy(monkeypatch):
    from types import SimpleNamespace

    from benchmarks.stt import stable_prefix

    monkeypatch.setattr(stable_prefix, "perf_counter_ns", lambda: 1_000_000)
    adapter = stable_prefix.StableFinalPrefix(
        SimpleNamespace(_event_ch=SimpleNamespace(send_nowait=lambda _: None)), 0
    )
    adapter.observe([{"text": "Chcel inú", "is_final": True}], 0)
    measured = adapter.finish("Chcel izbu")
    assert measured[0]["is_exact_token_prefix_of_final"] is False
    assert measured[0]["longest_common_token_prefix"] == 1
    assert measured[0]["prefix_token_accuracy"] == 0.5
    assert measured[0]["complete_final_word_count"] == 1

    adapter = stable_prefix.StableFinalPrefix(
        SimpleNamespace(_event_ch=SimpleNamespace(send_nowait=lambda _: None)), 0
    )
    adapter.observe([{"text": "Dobr", "is_final": True}], 0)
    partial = adapter.finish("Dobrý deň")[0]
    assert partial["is_character_prefix_of_final"]
    assert partial["ends_inside_final_word"]
    assert partial["complete_final_word_count"] == 0
    assert stable_prefix.threshold_leads([partial], "Dobrý deň")["words_1"] is None

    events = [
        {"complete_final_word_count": 1, "preflight_lead_ms": 1500},
        {"complete_final_word_count": 3, "preflight_lead_ms": 900},
        {"complete_final_word_count": 5, "preflight_lead_ms": 400},
    ]
    leads = stable_prefix.threshold_leads(
        events, "one two three four five six seven eight"
    )
    assert leads == {
        "words_1": 1500,
        "words_3": 900,
        "words_5": 400,
        "words_8": None,
        "fraction_25": 900,
        "fraction_50": 400,
        "fraction_75": None,
    }


def test_stable_prefix_summary_threshold_availability_and_signed_latency():
    from benchmarks.results.compare_stable_prefix import summarize

    row = {
        "status": "ok",
        "provider_frames": [{"final_token_count": 1, "nonfinal_token_count": 1}],
        "experimental_preflights": [
            {
                "stable_prefix_text": "Chcel",
                "preflight_lead_ms": 900,
                "prefix_token_accuracy": 1,
                "is_exact_token_prefix_of_final": True,
                "is_character_prefix_of_final": True,
                "ends_inside_final_word": False,
            }
        ],
        "experimental_preflight_count": 1,
        "threshold_leads_ms": {"words_1": 900, "words_3": None},
        "speculative_attempt_count": 1,
        "speculative_restart_count": 0,
        "speculative_attempt_reused": True,
        "speculative_attempt_invalidated": False,
        "llm_work_before_audio_end_ms": 500,
        "reused_llm_work_before_audio_end_ms": 500,
        "speculative_llm_start_ms": 100,
        "logical_audio_end_ms": 1000,
        "audio_end_to_first_llm_text_ms": -100,
    }
    summary = summarize([row, {"status": "error"}])
    assert (summary["successful_runs"], summary["failed_runs"]) == (1, 1)
    assert summary["thresholds"]["words_1"]["availability_rate"] == 1
    assert summary["thresholds"]["words_3"]["availability_rate"] == 0
    assert summary["llm_start_relative_to_audio_end_ms"]["median"] == -900
    assert summary["audio_end_to_first_llm_text_ms"]["median"] == -100
    assert summary["reuse_rate"] == 1
