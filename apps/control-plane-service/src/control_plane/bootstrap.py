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
from control_plane.application.integrations import IntegrationService
from control_plane.application.live_components import LiveComponentService
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
from control_plane.application.telephony import TelephonyService
from control_plane.application.tenant_configuration import TenantConfigurationService
from control_plane.domain.components import ComponentDefinitionRegistry
from control_plane.domain.frozen_components import default_component_definition_registry
from control_plane.domain.registries import (
    ArchitectureRegistry,
    DeploymentKindRegistry,
    IntegrationKindRegistry,
    ProviderKindRegistry,
)
from control_plane.infrastructure.encryption import CredentialCipher
from control_plane.infrastructure.persistence import Database
from control_plane.infrastructure.persistence.command_transactions import (
    component_command_scope,
)
from control_plane.infrastructure.persistence.credential_transactions import (
    credential_command_scope,
)
from control_plane.infrastructure.persistence.integration_transactions import (
    integration_command_scope,
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
from control_plane.infrastructure.persistence.telephony_transactions import (
    telephony_command_scope,
)
from control_plane.infrastructure.persistence.tenant_configuration_transactions import (
    tenant_configuration_command_scope,
    tenant_live_component_command_scope,
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
        registry = default_component_definition_registry()
    provider_registry = provider_registry or ProviderKindRegistry()
    architecture_registry = ArchitectureRegistry()
    deployment_registry = DeploymentKindRegistry()
    integration_registry = IntegrationKindRegistry()
    cipher = CredentialCipher(
        settings.control_plane_encryption_key.get_secret_value(),
        settings.control_plane_encryption_key_id,
    )
    integrations = (
        IntegrationService(
            integration_command_scope(database.sessions),
            integration_registry,
        )
        if isinstance(database, Database)
        else None
    )
    telephony = (
        TelephonyService(telephony_command_scope(database.sessions))
        if isinstance(database, Database)
        else None
    )
    components = (
        ComponentService(
            registry,
            cast(
                ComponentRepository,
                SqlAlchemyComponentRepository(database.sessions),
            ),
            component_command_scope(database.sessions),
            integrations.validate_actions_definition if integrations else None,
        )
        if isinstance(database, Database)
        else None
    )
    credentials = (
        CredentialService(credential_command_scope(database.sessions, cipher))
        if isinstance(database, Database)
        else None
    )
    providers = (
        ProviderService(
            provider_command_scope(database.sessions, cipher),
            provider_registry,
            deployment_registry,
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
            lambda _address: system_configuration_command_scope(
                database.sessions, cipher
            )(),
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
    tenant_scope = (
        tenant_configuration_command_scope(database.sessions)
        if isinstance(database, Database)
        else None
    )
    tenant_configuration = (
        TenantConfigurationService(
            registry,
            architecture_registry,
            tenant_scope,
        )
        if tenant_scope is not None
        else None
    )
    tenant_live_components = (
        LiveComponentService(
            registry,
            tenant_live_component_command_scope(tenant_scope),
            tenant_configuration.validate_live_component,
        )
        if tenant_scope is not None and tenant_configuration is not None
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
    execution_materialization = (
        ExecutionMaterializationService(
            database.sessions,
            cipher,
            SqlAlchemyExecutionSnapshotRepository(database.sessions),
            ExecutionResolver(registry, runtime_resolver),
            resolution_reader,
        )
        if isinstance(database, Database)
        and runtime_resolver is not None
        and resolution_reader is not None
        else None
    )
    runtime_materialization = (
        ExecutionSnapshotService(
            database.sessions,
            runtime_resolver,
            resolution_reader,
            SqlAlchemyExecutionSnapshotRepository(database.sessions),
            ExecutionResolver(registry, runtime_resolver),
            execution_materialization,
        )
        if runtime_resolver is not None and resolution_reader is not None
        else None
    )
    app = create_http_app(
        ServiceLifecycle(database, telemetry),
        components,
        runtime_resolver=runtime_resolver,
        runtime_materialization=runtime_materialization,
        execution_materialization=execution_materialization,
        credentials=credentials,
        providers=providers,
        system_configuration=system_configuration,
        live_components=live_components,
        platform_configuration=platform_configuration,
        platform_catalogs=platform_catalogs,
        integrations=integrations,
        telephony=telephony,
        tenant_configuration=tenant_configuration,
        tenant_live_components=tenant_live_components,
        component_registry=registry,
        architecture_registry=architecture_registry,
        provider_registry=provider_registry,
        deployment_registry=deployment_registry,
        integration_registry=integration_registry,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.telemetry = telemetry
    app.state.component_registry = registry
    app.state.architecture_registry = architecture_registry
    app.state.provider_registry = provider_registry
    app.state.deployment_registry = deployment_registry
    app.state.integration_registry = integration_registry
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
