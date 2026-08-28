import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentic_observability.bootstrap import (
    DEFAULT_HISTOGRAM_VIEWS,
    VOICE_DURATION_BUCKETS,
    VOICE_FAST_BUCKETS,
    TelemetryProviders,
)
from agentic_observability.config import TelemetryConfig
from livekit import agents
from livekit.agents.telemetry import tracer as livekit_tracer
from livekit.agents.types import USERDATA_TTS_STARTED_TIME
from livekit.agents.voice.agent import ModelSettings
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode
from voice_agent.observability import (
    LatencyInstrumentedAgent,
    LiveKitPrivacySpanProcessor,
    VoiceMetrics,
    configure_voice_telemetry,
    current_voice_telemetry,
    setup_voice_telemetry,
    shutdown_voice_telemetry,
)


@pytest.fixture(autouse=True)
def reset_voice_telemetry() -> None:
    shutdown_voice_telemetry()
    yield
    shutdown_voice_telemetry()


def _providers(
    *,
    spans: InMemorySpanExporter | None = None,
    metrics: InMemoryMetricReader | None = None,
) -> TelemetryProviders:
    resource = Resource.create({"service.name": "voice-agent"})
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(LiveKitPrivacySpanProcessor())
    if spans is not None:
        tracer_provider.add_span_processor(SimpleSpanProcessor(spans))
    meter_provider = MeterProvider(
        resource=resource,
        views=list(DEFAULT_HISTOGRAM_VIEWS),
        metric_readers=[metrics] if metrics is not None else [],
    )
    return TelemetryProviders(resource, tracer_provider, meter_provider)


def _metric_points(reader: InMemoryMetricReader) -> dict[str, list[object]]:
    result: dict[str, list[object]] = {}
    for resource_metric in reader.get_metrics_data().resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                result[metric.name] = list(metric.data.data_points)
    return result


def test_disabled_setup_keeps_runtime_unmodified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    monkeypatch.setattr(
        "voice_agent.observability.bootstrap",
        lambda *_args, **_kwargs: pytest.fail("disabled telemetry must not bootstrap"),
    )

    setup_voice_telemetry(None)  # type: ignore[arg-type]

    assert current_voice_telemetry() is None


def test_enabled_setup_uses_fixed_voice_service_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.setenv(
        "OTEL_RESOURCE_ATTRIBUTES",
        "service.version=test,deployment.environment.name=test,vcs.ref.head.revision=test",
    )
    monkeypatch.setenv("OTEL_SERVICE_NAME", "not-voice-agent")
    providers = _providers()
    configs: list[TelemetryConfig] = []

    def fake_bootstrap(
        config: TelemetryConfig, **_kwargs: object
    ) -> TelemetryProviders:
        configs.append(config)
        return providers

    monkeypatch.setattr("voice_agent.observability.bootstrap", fake_bootstrap)

    setup_voice_telemetry(None)  # type: ignore[arg-type]

    runtime = current_voice_telemetry()
    assert runtime is not None
    assert configs[0].service_name == "voice-agent"
    assert runtime.providers.resource.attributes["service.name"] == "voice-agent"


def test_native_livekit_span_is_exported_once_correlated_and_content_free() -> None:
    exporter = InMemorySpanExporter()
    runtime = configure_voice_telemetry(_providers(spans=exporter))
    assert runtime is not None
    call_id = uuid4()

    with livekit_tracer.start_as_current_span("agent_session") as span:
        span.set_attribute("lk.chat_ctx", "system prompt and chat history")
        span.set_attribute("lk.response.text", "assistant response")
        span.set_attribute("lk.function_tool.arguments", '{"customer":"secret"}')
        span.add_event("chat.item", {"content": "user transcript"})
        span.set_status(Status(StatusCode.ERROR, "tool result contains customer data"))
        runtime.set_session_correlation(call_id)

    shutdown_voice_telemetry()
    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    native_span = finished[0]
    assert native_span.instrumentation_scope.name == "livekit-agents"
    assert native_span.attributes["call.id"] == str(call_id)
    assert native_span.events == ()
    assert "system prompt" not in str(native_span.attributes)
    assert "assistant response" not in str(native_span.attributes)
    assert "customer" not in str(native_span.attributes)
    assert native_span.status.description is None
    assert current_voice_telemetry() is None
    shutdown_voice_telemetry()


def test_repeated_setup_does_not_duplicate_runtime_registration() -> None:
    exporter = InMemorySpanExporter()
    providers = _providers(spans=exporter)

    first = configure_voice_telemetry(providers)
    second = configure_voice_telemetry(providers)
    assert first is second
    assert first is not None

    with livekit_tracer.start_as_current_span("turn"):
        pass
    first.providers.force_flush()
    assert len(exporter.get_finished_spans()) == 1


def test_shutdown_allows_a_fresh_sequential_job_provider() -> None:
    first = configure_voice_telemetry(_providers())
    assert first is not None
    shutdown_voice_telemetry()

    second = configure_voice_telemetry(_providers())
    assert second is not None
    assert second is not first


def test_livekit_metrics_use_component_values_once_without_session_identifiers() -> (
    None
):
    reader = InMemoryMetricReader()
    providers = _providers(metrics=reader)
    meter = providers.meter("voice-agent")
    assert meter is not None
    metrics = VoiceMetrics(meter)

    metrics.record_turn(
        SimpleNamespace(
            metrics={
                "transcription_delay": 0.2,
                "end_of_turn_delay": 0.3,
                "on_user_turn_completed_delay": 0.4,
                "llm_node_ttft": 0.5,
                "tts_node_ttfb": 0.6,
                "e2e_latency": 0.7,
                "playback_latency": 0.08,
                "llm_metadata": {"model_provider": "azure", "model_name": "gpt"},
                "tts_metadata": {"model_provider": "elevenlabs", "model_name": "flash"},
            }
        )
    )
    metadata = SimpleNamespace(model_provider="azure", model_name="gpt")
    metrics.record_component_metric(
        SimpleNamespace(
            type="llm_metrics",
            metadata=metadata,
            cancelled=False,
            duration=1.0,
            ttft=0.2,
            prompt_tokens=10,
            prompt_cached_tokens=4,
            completion_tokens=3,
        )
    )
    metrics.record_component_metric(
        SimpleNamespace(
            type="stt_metrics",
            metadata=SimpleNamespace(model_provider="elevenlabs", model_name="scribe"),
            streamed=True,
            duration=9.0,
            audio_duration=2.0,
        )
    )
    metrics.record_component_metric(
        SimpleNamespace(
            type="tts_metrics",
            metadata=SimpleNamespace(model_provider="elevenlabs", model_name="flash"),
            cancelled=False,
            duration=1.1,
            ttfb=0.3,
            audio_duration=1.5,
            characters_count=12,
            acquire_time=0.04,
            connection_reused=True,
        )
    )
    metrics.record_component_error("tts", RuntimeError("provider failed"))
    providers.force_flush()

    points = _metric_points(reader)
    assert points["voice.turn.e2e_latency"][0].count == 1
    assert points["voice.llm.duration"][0].count == 1
    assert points["voice.llm.ttft"][0].count == 1
    assert points["voice.tts.duration"][0].count == 1
    assert points["voice.tts.ttfb"][0].count == 1
    assert len(points["voice.llm.requests"]) == 1
    assert points["voice.llm.input_tokens"][0].value == 10
    assert points["voice.llm.input_cached_tokens"][0].value == 4
    assert points["voice.llm.output_tokens"][0].value == 3
    assert "voice.stt.duration" not in points
    assert points["voice.stt.audio_duration"][0].value == 2
    assert points["voice.tts.characters"][0].value == 12
    assert points["voice.turn.playback_latency"][0].sum == 0.08
    assert points["voice.tts.connection.acquire_time"][0].sum == 0.04
    assert points["voice.tts.connection.requests"][0].value == 1
    assert points["voice.tts.connection.requests"][0].attributes["outcome"] == "reused"
    assert points["voice.component.errors"][0].value == 1
    assert all(
        not {"call.id", "conversation.id", "room.id", "participant.id"}
        & set(point.attributes)
        for metric_points in points.values()
        for point in metric_points
    )


def _prom_histogram_quantile(
    quantile: float, bounds: tuple[float, ...], bucket_counts: tuple[int, ...]
) -> float:
    cumulative = 0
    previous_count = 0
    previous_bound = 0.0
    rank = quantile * sum(bucket_counts)
    for bound, count in zip(bounds, bucket_counts, strict=True):
        cumulative += count
        if cumulative >= rank:
            return previous_bound + (rank - previous_count) / (
                cumulative - previous_count
            ) * (bound - previous_bound)
        previous_count = cumulative
        previous_bound = bound
    raise AssertionError("quantile fell outside histogram")


def test_default_buckets_explain_250_and_475_but_voice_views_do_not() -> None:
    old_reader = InMemoryMetricReader()
    old_provider = MeterProvider(metric_readers=[old_reader])
    old_histogram = old_provider.get_meter("old").create_histogram("old", unit="s")
    old_histogram.record(2.0)
    old_histogram.record(4.0)
    old_provider.force_flush()
    old_point = (
        old_reader.get_metrics_data()
        .resource_metrics[0]
        .scope_metrics[0]
        .metrics[0]
        .data.data_points[0]
    )
    assert old_point.explicit_bounds[:2] == (0.0, 5.0)
    assert _prom_histogram_quantile(0.50, (0.0, 5.0), (0, 2)) == 2.5
    assert _prom_histogram_quantile(0.95, (0.0, 5.0), (0, 2)) == 4.75
    old_provider.shutdown()

    reader = InMemoryMetricReader()
    provider = MeterProvider(
        views=list(DEFAULT_HISTOGRAM_VIEWS), metric_readers=[reader]
    )
    histogram = provider.get_meter("voice-agent").create_histogram(
        "voice.turn.e2e_latency", unit="s"
    )
    histogram.record(0.8)
    histogram.record(1.4)
    provider.force_flush()
    point = (
        reader.get_metrics_data()
        .resource_metrics[0]
        .scope_metrics[0]
        .metrics[0]
        .data.data_points[0]
    )
    assert point.explicit_bounds == VOICE_DURATION_BUCKETS
    assert point.sum == 2.2
    assert (
        _prom_histogram_quantile(0.95, point.explicit_bounds, point.bucket_counts)
        == 1.45
    )
    assert (
        _prom_histogram_quantile(0.95, point.explicit_bounds, point.bucket_counts)
        != 4.75
    )
    provider.shutdown()


def test_pipeline_latency_phases_are_correlated_without_identifier_attributes() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        views=list(DEFAULT_HISTOGRAM_VIEWS), metric_readers=[reader]
    )
    metrics = VoiceMetrics(provider.get_meter("voice-agent"))

    metrics.record_llm_request_started("speech-private", 10.0)
    metrics.record_llm_first_nonempty_text("speech-private", 11.2)
    metrics.record_tts_first_audio(
        "speech-private", tts_first_text_sent=11.5, tts_first_audio=11.7
    )
    provider.force_flush()

    points = _metric_points(reader)
    assert points["voice.turn.llm_usable_ttft"][0].sum == pytest.approx(1.2)
    assert points["voice.turn.llm_to_tts_dispatch_latency"][0].sum == pytest.approx(0.3)
    assert points["voice.turn.tts_effective_first_audio_latency"][
        0
    ].sum == pytest.approx(0.2)
    assert all(
        not point.attributes
        for name in (
            "voice.turn.llm_usable_ttft",
            "voice.turn.llm_to_tts_dispatch_latency",
            "voice.turn.tts_effective_first_audio_latency",
        )
        for point in points[name]
    )
    provider.shutdown()


@pytest.mark.asyncio
async def test_agent_node_hooks_capture_usable_text_and_provider_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []
    metrics = SimpleNamespace(
        record_llm_request_started=lambda *args: events.append(("llm_started", *args)),
        record_llm_first_nonempty_text=lambda *args: events.append(("llm_text", *args)),
        record_tts_first_audio=lambda speech_id, **kwargs: events.append(
            ("tts_audio", speech_id, kwargs)
        ),
    )

    async def fake_llm_node(*_args: object, **_kwargs: object):
        yield " "
        yield "Dobrý deň"

    async def fake_tts_node(*_args: object, **_kwargs: object):
        yield SimpleNamespace(userdata={USERDATA_TTS_STARTED_TIME: 11.5})

    async def text_input():
        yield "Dobrý deň"

    clock = iter((10.0, 11.0, 11.7))
    monkeypatch.setattr(agents.Agent, "llm_node", fake_llm_node)
    monkeypatch.setattr(agents.Agent, "tts_node", fake_tts_node)
    monkeypatch.setattr(
        "voice_agent.observability._current_speech_id", lambda: "speech-1"
    )
    monkeypatch.setattr(
        "voice_agent.observability.time.perf_counter", lambda: next(clock)
    )
    agent = LatencyInstrumentedAgent(metrics=metrics, instructions="test")  # type: ignore[arg-type]

    assert [
        chunk
        async for chunk in agent.llm_node(None, [], ModelSettings())  # type: ignore[arg-type]
    ] == [" ", "Dobrý deň"]
    assert (
        len([frame async for frame in agent.tts_node(text_input(), ModelSettings())])
        == 1
    )
    assert events == [
        ("llm_started", "speech-1", 10.0),
        ("llm_text", "speech-1", 11.0),
        (
            "tts_audio",
            "speech-1",
            {"tts_first_text_sent": 11.5, "tts_first_audio": 11.7},
        ),
    ]


@pytest.mark.asyncio
async def test_speculative_generation_metrics_follow_actual_handle_lifecycle() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        views=list(DEFAULT_HISTOGRAM_VIEWS), metric_readers=[reader]
    )
    metrics = VoiceMetrics(provider.get_meter("voice-agent"))

    class Session:
        def __init__(self) -> None:
            self.callbacks: dict[str, object] = {}

        def on(self, name: str, callback: object) -> None:
            self.callbacks[name] = callback

        def emit(self, name: str, event: object) -> None:
            self.callbacks[name](event)  # type: ignore[operator]

    class Handle:
        def __init__(self) -> None:
            self._scheduled_fut: asyncio.Future[None] = asyncio.Future()
            self._done_callbacks: list[object] = []

        @property
        def scheduled(self) -> bool:
            return self._scheduled_fut.done()

        def add_done_callback(self, callback: object) -> None:
            self._done_callbacks.append(callback)

        def finish(self) -> None:
            for callback in self._done_callbacks:
                callback(self)  # type: ignore[operator]

    session = Session()
    metrics.attach_speculative_generation(session)  # type: ignore[arg-type]

    reused = Handle()
    session.emit(
        "user_input_transcribed",
        SimpleNamespace(is_final=False, transcript="draft"),
    )
    session.emit(
        "speech_created",
        SimpleNamespace(source="generate_reply", speech_handle=reused),
    )
    reused._scheduled_fut.set_result(None)
    await asyncio.sleep(0)

    cancelled = Handle()
    session.emit(
        "user_input_transcribed",
        SimpleNamespace(is_final=False, transcript="draft"),
    )
    session.emit(
        "speech_created",
        SimpleNamespace(source="generate_reply", speech_handle=cancelled),
    )
    session.emit(
        "user_input_transcribed",
        SimpleNamespace(is_final=True, transcript="different"),
    )
    cancelled.finish()
    provider.force_flush()

    points = _metric_points(reader)
    assert points["voice.speculative_generation.started"][0].value == 2
    assert points["voice.speculative_generation.reused"][0].value == 1
    assert points["voice.speculative_generation.cancelled"][0].value == 1
    assert points["voice.speculative_generation.lead_time"][0].count == 1
    assert not points["voice.speculative_generation.started"][0].attributes
    assert not points["voice.speculative_generation.reused"][0].attributes
    assert points["voice.speculative_generation.cancelled"][0].attributes == {
        "reason": "final_transcript_mismatch"
    }
    assert not points["voice.speculative_generation.lead_time"][0].attributes
    provider.shutdown()


@pytest.mark.asyncio
async def test_speculative_cancellation_reason_is_superseded_interim() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        views=list(DEFAULT_HISTOGRAM_VIEWS), metric_readers=[reader]
    )
    metrics = VoiceMetrics(provider.get_meter("voice-agent"))

    class Session:
        def __init__(self) -> None:
            self.callbacks: dict[str, object] = {}

        def on(self, name: str, callback: object) -> None:
            self.callbacks[name] = callback

        def emit(self, name: str, event: object) -> None:
            self.callbacks[name](event)  # type: ignore[operator]

    class Handle:
        def __init__(self) -> None:
            self._scheduled_fut: asyncio.Future[None] = asyncio.Future()
            self._done_callbacks: list[object] = []

        @property
        def scheduled(self) -> bool:
            return self._scheduled_fut.done()

        def add_done_callback(self, callback: object) -> None:
            self._done_callbacks.append(callback)

        def finish(self) -> None:
            for callback in self._done_callbacks:
                callback(self)  # type: ignore[operator]

    session = Session()
    metrics.attach_speculative_generation(session)  # type: ignore[arg-type]
    first, second = Handle(), Handle()
    session.emit(
        "user_input_transcribed",
        SimpleNamespace(is_final=False, transcript="first"),
    )
    session.emit(
        "speech_created",
        SimpleNamespace(source="generate_reply", speech_handle=first),
    )
    session.emit(
        "user_input_transcribed",
        SimpleNamespace(is_final=False, transcript="second"),
    )
    session.emit(
        "speech_created",
        SimpleNamespace(source="generate_reply", speech_handle=second),
    )
    first.finish()
    provider.force_flush()
    points = _metric_points(reader)
    assert points["voice.speculative_generation.cancelled"][0].attributes == {
        "reason": "superseded_interim"
    }
    provider.shutdown()


def test_voice_latency_instruments_keep_distinct_units_and_boundaries() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        views=list(DEFAULT_HISTOGRAM_VIEWS), metric_readers=[reader]
    )
    meter = provider.get_meter("voice-agent")
    metrics = VoiceMetrics(meter)
    metrics.record_component_metric(
        SimpleNamespace(
            type="llm_metrics",
            metadata=SimpleNamespace(model_provider="azure", model_name="gpt"),
            cancelled=False,
            duration=2.2,
            ttft=0.4,
            prompt_tokens=0,
            prompt_cached_tokens=0,
            completion_tokens=0,
        )
    )
    metrics.record_component_metric(
        SimpleNamespace(
            type="tts_metrics",
            metadata=SimpleNamespace(model_provider="elevenlabs", model_name="flash"),
            cancelled=False,
            duration=1.4,
            ttfb=0.3,
            audio_duration=0,
            characters_count=0,
        )
    )
    provider.force_flush()
    points = _metric_points(reader)
    assert points["voice.llm.duration"][0].sum == 2.2
    assert points["voice.llm.ttft"][0].sum == 0.4
    assert points["voice.tts.duration"][0].sum == 1.4
    assert points["voice.tts.ttfb"][0].sum == 0.3
    assert points["voice.llm.duration"][0].explicit_bounds == VOICE_DURATION_BUCKETS
    assert points["voice.llm.ttft"][0].explicit_bounds == VOICE_FAST_BUCKETS
    assert points["voice.tts.duration"][0].explicit_bounds == VOICE_DURATION_BUCKETS
    assert points["voice.tts.ttfb"][0].explicit_bounds == VOICE_FAST_BUCKETS
    provider.shutdown()


def test_capability_metrics_use_canonical_low_cardinality_attributes() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        views=list(DEFAULT_HISTOGRAM_VIEWS), metric_readers=[reader]
    )
    metrics = VoiceMetrics(provider.get_meter("voice-agent"))
    metrics.record_capability_execution(
        name="reservation.check_availability",
        version="1",
        status="ok",
        duration_seconds=0.4,
    )
    metrics.record_capability_execution(
        name="calculator.calculate",
        version="1",
        status="ok",
        duration_seconds=0.01,
    )
    metrics.record_capability_execution(
        name="call.end",
        version="1",
        status="ok",
        duration_seconds=0.02,
    )
    metrics.record_capability_execution(
        name="calculator.calculate",
        version="1",
        status="failed",
        duration_seconds=0.01,
        error_type="division_by_zero",
    )
    provider.force_flush()
    points = _metric_points(reader)
    assert sum(point.value for point in points["capability.executions"]) == 4
    assert sum(point.value for point in points["capability.failures"]) == 1
    assert len(points["capability.execution.duration"]) == 4
    assert all(
        set(point.attributes)
        <= {
            "capability.name",
            "capability.version",
            "status",
            "error.type",
        }
        for point in points["capability.executions"]
        + points["capability.failures"]
        + points["capability.execution.duration"]
    )
    provider.shutdown()
