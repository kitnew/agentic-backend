import logging
from dataclasses import dataclass
from typing import Any, cast

from agentic_observability.bootstrap import bootstrap
from agentic_observability.config import TelemetryConfig
from agentic_observability.logging import install_trace_context_filter
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from control_plane import SERVICE_NAME
from control_plane.application.components import ComponentService
from control_plane.application.ports.repositories import ComponentRepository
from control_plane.domain.components import ComponentRegistry
from control_plane.infrastructure.messaging import NatsMessagePublisher
from control_plane.infrastructure.persistence import Database
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from control_plane.interfaces.http import create_http_app
from control_plane.runtime import ServiceLifecycle
from control_plane.settings import Settings


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    nats: NatsMessagePublisher | None = None,
    registry: ComponentRegistry | None = None,
) -> FastAPI:
    settings = settings or Settings()  # type: ignore[call-arg]
    database = database or Database(str(settings.database_url))
    nats = nats or NatsMessagePublisher(settings.nats_url)
    telemetry = _configure_observability(settings)
    registry = registry or ComponentRegistry()
    components = (
        ComponentService(
            registry,
            cast(
                ComponentRepository,
                SqlAlchemyComponentRepository(database.sessions),
            ),
        )
        if isinstance(database, Database)
        else None
    )
    app = create_http_app(ServiceLifecycle(database, nats, telemetry), components)
    app.state.settings = settings
    app.state.database = database
    app.state.nats = nats
    app.state.telemetry = telemetry
    app.state.component_registry = registry
    if settings.otel_enabled and telemetry.tracer_provider and telemetry.meter_provider:
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=telemetry.tracer_provider,
            meter_provider=telemetry.meter_provider,
        )
    return app


@dataclass(slots=True)
class NoopTelemetry:
    tracer_provider: Any = None
    meter_provider: Any = None

    def shutdown(self) -> bool:
        return True


def _configure_observability(settings: Settings) -> Any:
    if not settings.otel_enabled:
        return NoopTelemetry()
    telemetry = bootstrap(TelemetryConfig.from_env(default_service_name=SERVICE_NAME))
    install_trace_context_filter(logging.getLogger().handlers)
    return telemetry
