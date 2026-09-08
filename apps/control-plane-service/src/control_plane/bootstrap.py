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
from control_plane.application.credentials import CredentialService
from control_plane.application.execution_materialization import (
    ExecutionMaterializationService,
)
from control_plane.application.execution_resolver import ExecutionResolver
from control_plane.application.live_components import LiveComponentService
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.application.platform_catalogs import PlatformCatalogService
from control_plane.application.platform_configuration import (
    PlatformConfigurationService,
)
from control_plane.application.ports.repositories import ComponentRepository
from control_plane.application.providers import ProviderService
from control_plane.application.runtime_materialization import (
    ExecutionSnapshotService,
)
from control_plane.application.runtime_resolver import RuntimeResolver
from control_plane.application.system_configuration import SystemConfigurationService
from control_plane.domain.agent_components import register_agent_components
from control_plane.domain.capabilities import register_capability_components
from control_plane.domain.components import ComponentDefinitionRegistry
from control_plane.domain.knowledge_components import register_knowledge_components
from control_plane.domain.post_call import register_post_call_components
from control_plane.domain.prompt_components import register_prompt_components
from control_plane.domain.registries import DeploymentKindRegistry, ProviderKindRegistry
from control_plane.domain.runtime_components import register_runtime_components
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence import Database
from control_plane.infrastructure.persistence.command_transactions import (
    component_command_scope,
)
from control_plane.infrastructure.persistence.credential_transactions import (
    credential_command_scope,
)
from control_plane.infrastructure.persistence.managed_resources import (
    SqlAlchemyManagedResourceRepository,
)
from control_plane.infrastructure.persistence.platform_configuration_transactions import (
    platform_configuration_command_scope,
)
from control_plane.infrastructure.persistence.provider_transactions import (
    provider_command_scope,
)
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from control_plane.infrastructure.persistence.runtime_execution_snapshots import (
    SqlAlchemyExecutionSnapshotRepository,
)
from control_plane.infrastructure.persistence.runtime_resolution import (
    SqlAlchemyRuntimeResolutionReader,
)
from control_plane.infrastructure.persistence.system_configuration_transactions import (
    system_configuration_command_scope,
)
from control_plane.infrastructure.provider_validation import HttpProviderValidator
from control_plane.interfaces.http import create_http_app
from control_plane.runtime import ServiceLifecycle
from control_plane.settings import Settings


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    registry: ComponentDefinitionRegistry | None = None,
    provider_registry: ProviderKindRegistry | None = None,
) -> FastAPI:
    settings = settings or Settings()  # type: ignore[call-arg]
    database = database or Database(str(settings.database_url))
    telemetry = _configure_observability(settings)
    if registry is None:
        registry = ComponentDefinitionRegistry()
        register_runtime_components(registry)
        register_agent_components(registry)
        register_prompt_components(registry)
        register_knowledge_components(registry)
        register_capability_components(registry)
        register_post_call_components(registry)
        registry.freeze()
    provider_registry = provider_registry or ProviderKindRegistry()
    components = (
        ComponentService(
            registry,
            cast(
                ComponentRepository,
                SqlAlchemyComponentRepository(database.sessions),
            ),
            component_command_scope(database.sessions),
        )
        if isinstance(database, Database)
        else None
    )
    cipher = CredentialCipher(
        settings.control_plane_encryption_key.get_secret_value(),
        settings.control_plane_encryption_key_id,
    )
    credentials = (
        CredentialService(credential_command_scope(database.sessions, cipher))
        if isinstance(database, Database)
        else None
    )
    managed_resources = (
        ManagedResourceService(SqlAlchemyManagedResourceRepository(database.sessions))
        if isinstance(database, Database)
        else None
    )
    providers = (
        ProviderService(
            provider_command_scope(database.sessions, cipher),
            provider_registry,
            DeploymentKindRegistry(),
            HttpProviderValidator(),
        )
        if isinstance(database, Database)
        else None
    )
    system_configuration = (
        SystemConfigurationService(
            registry, system_configuration_command_scope(database.sessions, cipher)
        )
        if isinstance(database, Database)
        else None
    )
    live_components = (
        LiveComponentService(
            registry,
            system_configuration_command_scope(database.sessions, cipher),
            system_configuration.validate_live_component,
        )
        if isinstance(database, Database) and system_configuration is not None
        else None
    )
    platform_scope = (
        platform_configuration_command_scope(database.sessions)
        if isinstance(database, Database)
        else None
    )
    platform_configuration = (
        PlatformConfigurationService(registry, platform_scope)
        if platform_scope is not None
        else None
    )
    platform_catalogs = (
        PlatformCatalogService(platform_scope) if platform_scope is not None else None
    )
    execution_materialization = (
        ExecutionMaterializationService(
            database.sessions,
            cipher,
            SqlAlchemyExecutionSnapshotRepository(database.sessions),
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
        ExecutionSnapshotService(
            database.sessions,
            runtime_resolver,
            resolution_reader,
            SqlAlchemyExecutionSnapshotRepository(database.sessions),
            ExecutionResolver(registry, runtime_resolver),
        )
        if runtime_resolver is not None and resolution_reader is not None
        else None
    )
    app = create_http_app(
        ServiceLifecycle(database, telemetry),
        components,
        managed_resources,
        runtime_resolver,
        runtime_materialization,
        execution_materialization,
        credentials,
        providers,
        system_configuration,
        live_components,
        platform_configuration,
        platform_catalogs,
    )
    app.state.settings = settings
    app.state.database = database
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
