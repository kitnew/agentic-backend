"""Application-owned runtime instrumentation."""

from __future__ import annotations

import logging
from typing import cast

from agentic_observability.bootstrap import TelemetryProviders
from agentic_observability.logging import install_trace_context_filter
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import __version__ as sqlalchemy_version
from opentelemetry.instrumentation.sqlalchemy.engine import EngineTracer
from opentelemetry.metrics import MeterProvider, get_meter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.semconv.metrics import MetricInstruments
from redis.asyncio import Redis

from backend_core.platform.database import Database


def instrument_app(app: FastAPI, telemetry: TelemetryProviders) -> None:
    tracer_provider, meter_provider = _providers(telemetry)
    if not getattr(app.state, "otel_fastapi_instrumented", False):
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
        )
        app.state.otel_fastapi_instrumented = True
    if not getattr(app.state, "otel_sqlalchemy_instrumented", False):
        _instrument_sqlalchemy_engine(
            app.state.database, tracer_provider, meter_provider
        )
        app.state.otel_sqlalchemy_instrumented = True
    install_trace_context_filter(logging.getLogger().handlers)


def instrument_redis_client(redis: Redis, telemetry: TelemetryProviders) -> None:
    tracer_provider, _ = _providers(telemetry)
    RedisInstrumentor.instrument_client(redis, tracer_provider=tracer_provider)


def _providers(telemetry: TelemetryProviders) -> tuple[TracerProvider, MeterProvider]:
    if telemetry.tracer_provider is None or telemetry.meter_provider is None:
        raise ValueError("enabled telemetry requires explicit providers")
    return (
        cast(TracerProvider, telemetry.tracer_provider),
        cast(MeterProvider, telemetry.meter_provider),
    )


def _instrument_sqlalchemy_engine(
    database: Database,
    tracer_provider: TracerProvider,
    meter_provider: MeterProvider,
) -> None:
    tracer = tracer_provider.get_tracer(
        "opentelemetry.instrumentation.sqlalchemy", sqlalchemy_version
    )
    meter = get_meter(
        "opentelemetry.instrumentation.sqlalchemy",
        sqlalchemy_version,
        meter_provider,
        schema_url="https://opentelemetry.io/schemas/1.11.0",
    )
    EngineTracer(
        tracer,
        database.instrumentable_engine,
        meter.create_up_down_counter(
            MetricInstruments.DB_CLIENT_CONNECTIONS_USAGE,
            unit="connections",
            description="The number of connections that are currently in state described by the state attribute.",
        ),
    )
