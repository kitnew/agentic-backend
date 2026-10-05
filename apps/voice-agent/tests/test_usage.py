from types import SimpleNamespace
from uuid import uuid4

import pytest
from livekit.agents.metrics.usage import (
    AgentSessionUsage,
    LLMModelUsage,
    STTModelUsage,
    TTSModelUsage,
)
from voice_agent.providers import _create_stt
from voice_agent.usage import CallUsageReporter


class FakeSession:
    def __init__(self, usage):
        self.usage = AgentSessionUsage(model_usage=usage)
        self.handlers = {}

    def on(self, name, handler):
        self.handlers[name] = handler


class FakeBackend:
    def __init__(self, fail=False):
        self.reports = []
        self.fail = fail

    async def report_ai_usage(self, call_id, report):
        if self.fail:
            raise OSError("backend unavailable")
        self.reports.append(report)


def reporter(usage, *, fail=False):
    session = FakeSession(usage)
    backend = FakeBackend(fail)
    metrics = SimpleNamespace(failures=0)
    metrics.record_usage_persistence_failure = lambda: setattr(
        metrics, "failures", metrics.failures + 1
    )
    return (
        CallUsageReporter(
            backend, uuid4(), session, {"llm": "azure_openai", "stt": "soniox"}, metrics
        ),
        session,
        backend,
        metrics,
    )


def test_snapshot_collects_models_cached_tokens_and_standalone_stt():
    usage = [
        LLMModelUsage(
            provider="openai",
            model="gpt-a",
            input_tokens=100,
            input_cached_tokens=30,
            output_tokens=20,
        ),
        LLMModelUsage(provider="openai", model="gpt-b", input_tokens=7),
        STTModelUsage(
            provider="soniox",
            model="stt-rt-v5",
            input_tokens=7,
            input_audio_tokens=5,
            audio_duration=12.5,
        ),
        TTSModelUsage(
            provider="elevenlabs",
            model="eleven_v3",
            characters_count=80,
            audio_duration=3.0,
        ),
    ]
    meter, _, _, _ = reporter(usage)
    rows = meter.snapshot().usage
    assert len(rows) == 4
    assert rows[0].provider == "azure_openai"
    assert rows[0].counters["input_cached_tokens"] == 30
    assert rows[1].model == "gpt-b"
    assert rows[2].counters["audio_duration"] == 12.5
    assert rows[2].counters["input_audio_tokens"] == 5
    assert rows[2].source == "livekit_session_1_8_4"
    assert rows[3].counters["characters_count"] == 80


def test_soniox_stream_uses_call_id_for_provider_reconciliation():
    call_id = uuid4()
    stt = _create_stt(
        {
            "provider_kind": "soniox",
            "deployment_config": {"model": "stt-rt-v5"},
            "connection_config": {"region": "eu"},
        },
        "sk-SK",
        "secret",
        call_id=call_id,
    )
    assert stt._params.client_reference_id == str(call_id)


@pytest.mark.asyncio
async def test_final_flush_sends_latest_cumulative_snapshot_once():
    meter, session, backend, _ = reporter(
        [STTModelUsage(provider="soniox", model="stt-rt-v5", audio_duration=1)]
    )
    session.handlers["session_usage_updated"](object())
    session.usage = AgentSessionUsage(
        model_usage=[
            STTModelUsage(provider="soniox", model="stt-rt-v5", audio_duration=3)
        ]
    )
    await meter.flush()
    assert len(backend.reports) == 1
    assert backend.reports[0].usage[0].counters["audio_duration"] == 3


@pytest.mark.asyncio
async def test_persistence_failure_never_escapes_flush():
    meter, _, _, metrics = reporter(
        [LLMModelUsage(provider="openai", model="gpt-a", input_tokens=1)], fail=True
    )
    await meter.flush()
    assert metrics.failures == 1
