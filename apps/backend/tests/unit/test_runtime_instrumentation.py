import pytest
from agentic_observability.bootstrap import TelemetryProviders
from backend_core.bootstrap import instrumentation
from backend_core.platform.livekit import LiveKitAdapter
from fastapi import FastAPI
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider


def providers() -> TelemetryProviders:
    return TelemetryProviders(Resource.create({}), TracerProvider(), MeterProvider())


def test_fastapi_and_specific_sqlalchemy_engine_are_instrumented_once(monkeypatch) -> None:
    app = FastAPI()
    app.state.database = object()
    fastapi_calls: list[FastAPI] = []
    engine_calls: list[object] = []
    monkeypatch.setattr(
        instrumentation.FastAPIInstrumentor,
        "instrument_app",
        lambda app, **_: fastapi_calls.append(app),
    )
    monkeypatch.setattr(
        instrumentation,
        "_instrument_sqlalchemy_engine",
        lambda database, *_: engine_calls.append(database),
    )

    telemetry = providers()
    instrumentation.instrument_app(app, telemetry)
    instrumentation.instrument_app(app, telemetry)

    assert fastapi_calls == [app]
    assert engine_calls == [app.state.database]
    telemetry.shutdown()


def test_only_the_created_redis_client_is_instrumented(monkeypatch) -> None:
    calls: list[object] = []
    redis = object()
    monkeypatch.setattr(
        instrumentation.RedisInstrumentor,
        "instrument_client",
        lambda client, **_: calls.append(client),
    )

    telemetry = providers()
    instrumentation.instrument_redis_client(redis, telemetry)  # type: ignore[arg-type]

    assert calls == [redis]
    telemetry.shutdown()


def test_sqlalchemy_instrumentation_receives_only_database_engine(monkeypatch) -> None:
    engine = object()
    calls: list[object] = []

    class Database:
        instrumentable_engine = engine

    monkeypatch.setattr(
        instrumentation,
        "EngineTracer",
        lambda _tracer, actual_engine, _counter: calls.append(actual_engine),
    )
    telemetry = providers()
    instrumentation._instrument_sqlalchemy_engine(
        Database(),  # type: ignore[arg-type]
        telemetry.tracer_provider,  # type: ignore[arg-type]
        telemetry.meter_provider,  # type: ignore[arg-type]
    )

    assert calls == [engine]
    telemetry.shutdown()


@pytest.mark.asyncio
async def test_livekit_uses_an_application_owned_instrumented_aiohttp_session(
    monkeypatch,
) -> None:
    sessions: list[object] = []

    class Client:
        def __init__(self, *args, session=None) -> None:
            sessions.append(session)

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr("backend_core.platform.livekit.api.LiveKitAPI", Client)
    adapter = LiveKitAdapter(
        url="http://livekit",
        api_key="key",
        api_secret="secret",
        participant_token_ttl_seconds=600,
    )
    telemetry = providers()
    adapter.instrument_http(telemetry.tracer_provider, telemetry.meter_provider)

    await adapter.start()

    assert sessions[0] is not None
    assert sessions[0]._trace_configs  # type: ignore[attr-defined]
    await adapter.aclose()
    telemetry.shutdown()
