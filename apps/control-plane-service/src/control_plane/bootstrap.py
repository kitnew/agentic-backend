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
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.application.ports.repositories import ComponentRepository
from control_plane.application.runtime_materialization import (
    RuntimeMaterializationService,
)
from control_plane.application.runtime_resolver import RuntimeResolver
from control_plane.domain.components import ComponentRegistry
from control_plane.domain.prompt_components import register_prompt_components
from control_plane.domain.providers import ProviderRegistry, default_provider_registry
from control_plane.domain.runtime_components import register_runtime_components
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.messaging import NatsMessagePublisher, OutboxRelay
from control_plane.infrastructure.persistence import Database
from control_plane.infrastructure.persistence.managed_resources import (
    SqlAlchemyManagedResourceRepository,
)
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from control_plane.infrastructure.persistence.runtime_execution_snapshots import (
    SqlAlchemyRuntimeExecutionSnapshotRepository,
)
from control_plane.infrastructure.persistence.runtime_resolution import (
    SqlAlchemyRuntimeResolutionReader,
)
from control_plane.interfaces.http import create_http_app
from control_plane.runtime import ServiceLifecycle
from control_plane.settings import Settings


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    nats: NatsMessagePublisher | None = None,
    registry: ComponentRegistry | None = None,
    relay: OutboxRelay | None = None,
    provider_registry: ProviderRegistry | None = None,
) -> FastAPI:
    settings = settings or Settings()  # type: ignore[call-arg]
    database = database or Database(str(settings.database_url))
    nats = nats or NatsMessagePublisher(settings.nats_url)
    relay = relay or OutboxRelay(
        database.sessions, nats, settings.outbox_poll_interval_seconds
    )
    telemetry = _configure_observability(settings)
    if registry is None:
        registry = ComponentRegistry()
        register_runtime_components(registry)
        register_prompt_components(registry)
    provider_registry = provider_registry or default_provider_registry()
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
    managed_resources = (
        ManagedResourceService(
            provider_registry,
            SqlAlchemyManagedResourceRepository(
                database.sessions,
                CredentialCipher(
                    settings.control_plane_encryption_key.get_secret_value(),
                    settings.control_plane_encryption_key_id,
                ),
            ),
        )
        if isinstance(database, Database)
        else None
    )
    resolution_reader = (
        SqlAlchemyRuntimeResolutionReader(database.sessions)
        if isinstance(database, Database)
        else None
    )
    runtime_resolver = (
        RuntimeResolver(
            registry,
            provider_registry,
            resolution_reader,
        )
        if resolution_reader is not None
        else None
    )
    runtime_materialization = (
        RuntimeMaterializationService(
            database.sessions,
            runtime_resolver,
            resolution_reader,
            SqlAlchemyRuntimeExecutionSnapshotRepository(database.sessions),
        )
        if runtime_resolver is not None and resolution_reader is not None
        else None
    )
    app = create_http_app(
        ServiceLifecycle(database, nats, relay, telemetry),
        components,
        managed_resources,
        runtime_resolver,
        runtime_materialization,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.nats = nats
    app.state.outbox_relay = relay
    app.state.telemetry = telemetry
    app.state.component_registry = registry
    app.state.provider_registry = provider_registry
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
