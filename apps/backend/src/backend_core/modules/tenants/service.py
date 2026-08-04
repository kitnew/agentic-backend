from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

from contracts import (
    TenantCapabilityProfile,
    TenantConfig,
    TenantConfigV1,
    TenantConfigV2,
)
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from backend_core.modules.capabilities.domain import (
    CapabilityValidationError,
    compile_plan,
    definition,
    normalize_input,
    validate_agent_input,
    validate_agent_schema,
    validate_business_input,
)
from backend_core.modules.integrations.models import (
    IntegrationConnectionStatus,
    IntegrationProvider,
)
from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.modules.tenants.errors import (
    ActiveConfigNotFoundError,
    ActiveDraftExistsError,
    ConfigRevisionImmutableError,
    ConfigRevisionNotFoundError,
    ConfigRevisionVersionConflictError,
    InboundRouteDidConflictError,
    InboundRouteNotFoundError,
    InboundRouteUnavailableError,
    InvalidTenantConfigError,
    PromptBundleActiveDraftExistsError,
    PromptBundleRevisionImmutableError,
    PromptBundleRevisionNotFoundError,
    PromptBundleRevisionVersionConflictError,
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    InboundRoute,
    PromptBundleRevision,
    PromptBundleRevisionStatus,
    Tenant,
    TenantConfigRevision,
)
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    InboundRouteRepository,
    PromptBundleRevisionRepository,
    TenantRepository,
)
from backend_core.modules.tenants.schemas import (
    CreateDraftRequest,
    CreateInboundRouteRequest,
    CreatePromptBundleDraftRequest,
    CreateTenantRequest,
    UpdateDraftRequest,
    UpdateInboundRouteRequest,
    UpdatePromptBundleDraftRequest,
    ValidationIssue,
)


class TenantService:
    def __init__(self, repository: TenantRepository) -> None:
        self._repository = repository

    async def create(self, data: CreateTenantRequest) -> Tenant:
        if await self._repository.get_by_slug(data.slug):
            raise TenantSlugConflictError

        tenant = Tenant(**data.model_dump())
        try:
            return await self._repository.add(tenant)
        except IntegrityError as error:
            raise TenantSlugConflictError from error

    async def get(self, tenant_id: UUID) -> Tenant:
        tenant = await self._repository.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        return tenant

    async def list(self, *, offset: int, limit: int) -> list[Tenant]:
        return await self._repository.list(offset=offset, limit=limit)


class InboundRouteService:
    def __init__(
        self,
        tenants: TenantRepository,
        routes: InboundRouteRepository,
    ) -> None:
        self._tenants = tenants
        self._routes = routes

    async def create(
        self,
        tenant_id: UUID,
        data: CreateInboundRouteRequest,
    ) -> InboundRoute:
        if await self._tenants.get(tenant_id) is None:
            raise TenantNotFoundError
        route = InboundRoute(tenant_id=tenant_id, **data.model_dump())
        try:
            return await self._routes.add(route)
        except IntegrityError as error:
            raise InboundRouteDidConflictError from error

    async def list(self, tenant_id: UUID) -> list[InboundRoute]:
        if await self._tenants.get(tenant_id) is None:
            raise TenantNotFoundError
        return await self._routes.list(tenant_id)

    async def update(
        self,
        tenant_id: UUID,
        route_id: UUID,
        data: UpdateInboundRouteRequest,
    ) -> InboundRoute:
        route = await self._routes.get(tenant_id, route_id)
        if route is None:
            raise InboundRouteNotFoundError
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(route, field, value)
        try:
            await self._routes.flush()
            await self._routes.refresh(route)
        except IntegrityError as error:
            raise InboundRouteDidConflictError from error
        return route

    async def resolve(
        self,
        normalized_did: str,
    ) -> tuple[Tenant, TenantConfigRevision]:
        resolution = await self._routes.resolve(normalized_did)
        if resolution is None:
            raise InboundRouteUnavailableError
        return resolution


class PromptBundleService:
    def __init__(
        self,
        tenants: TenantRepository,
        revisions: PromptBundleRevisionRepository,
    ) -> None:
        self._tenants = tenants
        self._revisions = revisions

    async def create_draft(
        self,
        tenant_id: UUID,
        data: CreatePromptBundleDraftRequest,
    ) -> PromptBundleRevision:
        if await self._tenants.get_for_update(tenant_id) is None:
            raise TenantNotFoundError
        if await self._revisions.get_draft(tenant_id):
            raise PromptBundleActiveDraftExistsError
        revision = PromptBundleRevision(
            tenant_id=tenant_id,
            revision_number=await self._revisions.next_revision_number(tenant_id),
            **data.model_dump(),
        )
        try:
            return await self._revisions.add(revision)
        except IntegrityError as error:
            raise PromptBundleActiveDraftExistsError from error

    async def update_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
        data: UpdatePromptBundleDraftRequest,
        expected_version: int,
    ) -> PromptBundleRevision:
        revision = await self._revision_for_update(tenant_id, revision_id)
        if revision.status is not PromptBundleRevisionStatus.DRAFT:
            raise PromptBundleRevisionImmutableError
        if revision.version != expected_version:
            raise PromptBundleRevisionVersionConflictError
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(revision, field, value)
        revision.version += 1
        await self._revisions.flush()
        return revision

    async def publish(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> PromptBundleRevision:
        revision = await self._revision_for_update(tenant_id, revision_id)
        if revision.status is not PromptBundleRevisionStatus.DRAFT:
            raise PromptBundleRevisionImmutableError
        revision.status = PromptBundleRevisionStatus.PUBLISHED
        revision.published_at = datetime.now(UTC)
        await self._revisions.flush()
        return revision

    async def list(self, tenant_id: UUID) -> list[PromptBundleRevision]:
        if await self._tenants.get(tenant_id) is None:
            raise TenantNotFoundError
        return await self._revisions.list(tenant_id)

    async def _revision_for_update(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> PromptBundleRevision:
        revision = await self._revisions.get_for_update(tenant_id, revision_id)
        if revision is None:
            raise PromptBundleRevisionNotFoundError
        return revision


class ConfigUseCases:
    def __init__(
        self,
        tenants: TenantRepository,
        revisions: ConfigRevisionRepository,
        prompt_bundles: PromptBundleRevisionRepository,
        connections: IntegrationConnectionRepository,
    ) -> None:
        self._tenants = tenants
        self._revisions = revisions
        self._prompt_bundles = prompt_bundles
        self._connections = connections

    async def create_config_draft(
        self,
        tenant_id: UUID,
        data: CreateDraftRequest,
    ) -> TenantConfigRevision:
        tenant = await self._tenant_for_update(tenant_id)
        await self._ensure_no_draft(tenant_id)

        config = data.config
        schema_version = data.schema_version
        if config is None and tenant.active_config_revision_id:
            source = await self._revision(
                tenant_id,
                tenant.active_config_revision_id,
            )
            config = deepcopy(source.config)
            schema_version = schema_version or source.schema_version

        config = config or {}
        if schema_version is None:
            config_schema_version = config.get("schema_version")
            schema_version = (
                config_schema_version
                if type(config_schema_version) is int and config_schema_version > 0
                else 1
            )

        revision = TenantConfigRevision(
            tenant_id=tenant_id,
            revision_number=await self._revisions.next_revision_number(tenant_id),
            schema_version=schema_version,
            config=config,
            created_by=None,
            comment=data.comment,
        )
        try:
            return await self._revisions.add(revision)
        except IntegrityError as error:
            raise ActiveDraftExistsError from error

    async def update_config_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
        data: UpdateDraftRequest,
        expected_version: int,
    ) -> TenantConfigRevision:
        revision = await self._revision_for_update(tenant_id, revision_id)
        if revision.status is not ConfigRevisionStatus.DRAFT:
            raise ConfigRevisionImmutableError
        if revision.version != expected_version:
            raise ConfigRevisionVersionConflictError

        changes = data.model_dump(exclude_unset=True)
        if "config" in changes and "schema_version" not in changes:
            config_schema_version = changes["config"].get("schema_version")
            if type(config_schema_version) is int and config_schema_version > 0:
                changes["schema_version"] = config_schema_version

        for field, value in changes.items():
            setattr(revision, field, value)
        revision.version += 1
        await self._revisions.flush()
        return revision

    async def get_config_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision:
        revision = await self._revision(tenant_id, revision_id)
        if revision.status is not ConfigRevisionStatus.DRAFT:
            raise ConfigRevisionImmutableError
        return revision

    async def validate_config_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> list[ValidationIssue]:
        revision = await self._revision(tenant_id, revision_id)
        if revision.status is not ConfigRevisionStatus.DRAFT:
            raise ConfigRevisionImmutableError
        _, errors = await self._validate_config(revision)
        return errors

    async def publish_config_draft(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision:
        tenant = await self._tenant_for_update(tenant_id)
        revision = await self._revision_for_update(tenant_id, revision_id)
        if revision.status is not ConfigRevisionStatus.DRAFT:
            raise ConfigRevisionImmutableError
        _, errors = await self._validate_config(revision)
        if errors:
            raise InvalidTenantConfigError([error.model_dump() for error in errors])

        if tenant.active_config_revision_id:
            active = await self._revision_for_update(
                tenant_id,
                tenant.active_config_revision_id,
            )
            active.status = ConfigRevisionStatus.ARCHIVED

        revision.status = ConfigRevisionStatus.PUBLISHED
        revision.published_at = datetime.now(UTC)
        tenant.active_config_revision_id = revision.id
        await self._revisions.flush()
        return revision

    async def list_config_revisions(
        self,
        tenant_id: UUID,
    ) -> list[TenantConfigRevision]:
        if await self._tenants.get(tenant_id) is None:
            raise TenantNotFoundError
        return await self._revisions.list(tenant_id)

    async def get_active_config(
        self,
        tenant_id: UUID,
    ) -> tuple[TenantConfigRevision, TenantConfig]:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        return await self._active_config(tenant)

    async def get_internal_active_config(
        self,
        tenant_id: UUID,
    ) -> tuple[TenantConfigRevision, TenantConfig]:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None or not tenant.is_available_in_runtime:
            raise TenantNotFoundError
        return await self._active_config(tenant)

    async def _active_config(
        self,
        tenant: Tenant,
    ) -> tuple[TenantConfigRevision, TenantConfig]:
        if tenant.active_config_revision_id is None:
            raise ActiveConfigNotFoundError

        revision = await self._revision(
            tenant.id,
            tenant.active_config_revision_id,
        )
        if (
            revision.status is not ConfigRevisionStatus.PUBLISHED
            or revision.published_at is None
        ):
            raise ActiveConfigNotFoundError
        config, errors = await self._validate_config(revision)
        if config is None:
            raise InvalidTenantConfigError([error.model_dump() for error in errors])
        return revision, config

    async def _tenant_for_update(self, tenant_id: UUID) -> Tenant:
        tenant = await self._tenants.get_for_update(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        return tenant

    async def _revision(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision:
        revision = await self._revisions.get(tenant_id, revision_id)
        if revision is None:
            raise ConfigRevisionNotFoundError
        return revision

    async def _revision_for_update(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision:
        revision = await self._revisions.get_for_update(tenant_id, revision_id)
        if revision is None:
            raise ConfigRevisionNotFoundError
        return revision

    async def _ensure_no_draft(self, tenant_id: UUID) -> None:
        if await self._revisions.get_draft(tenant_id):
            raise ActiveDraftExistsError

    async def _validate_config(
        self,
        revision: TenantConfigRevision,
    ) -> tuple[TenantConfig | None, list[ValidationIssue]]:
        if revision.schema_version not in (1, 2):
            return (
                None,
                [
                    ValidationIssue(
                        path="schema_version",
                        code="unsupported_schema_version",
                        message="Only schema_version 1 and 2 are supported",
                    )
                ],
            )
        try:
            config: TenantConfig
            if revision.schema_version == 1:
                config = TenantConfigV1.model_validate(revision.config)
            else:
                config = TenantConfigV2.model_validate(revision.config)
        except ValidationError as error:
            return (
                None,
                [
                    ValidationIssue(
                        path=".".join(str(part) for part in item["loc"]),
                        code=item["type"],
                        message=item["msg"],
                    )
                    for item in error.errors(
                        include_url=False,
                        include_context=False,
                        include_input=False,
                    )
                ],
            )
        if config.schema_version != revision.schema_version:
            return (
                None,
                [
                    ValidationIssue(
                        path="schema_version",
                        code="schema_version_mismatch",
                        message="Config and revision schema versions differ",
                    )
                ],
            )
        if isinstance(config, TenantConfigV2):
            prompt_revision = await self._prompt_bundles.get(
                revision.tenant_id,
                config.prompt_bundle_revision_id,
            )
            if prompt_revision is None:
                return (
                    None,
                    [
                        ValidationIssue(
                            path="prompt_bundle_revision_id",
                            code="prompt_bundle_revision_not_found",
                            message="Prompt bundle revision does not belong to tenant",
                        )
                    ],
                )
            if prompt_revision.status is not PromptBundleRevisionStatus.PUBLISHED:
                return (
                    None,
                    [
                        ValidationIssue(
                            path="prompt_bundle_revision_id",
                            code="prompt_bundle_revision_not_published",
                            message="Prompt bundle revision is not published",
                        )
                    ],
                )
            capability_errors = await self._validate_capabilities(
                revision.tenant_id,
                config,
            )
            if capability_errors:
                return None, capability_errors
        return config, []

    async def _validate_capabilities(
        self,
        tenant_id: UUID,
        config: TenantConfigV2,
    ) -> list[ValidationIssue]:
        errors: list[ValidationIssue] = []
        for semantic_key, raw_profile in config.capabilities.items():
            if not isinstance(raw_profile, TenantCapabilityProfile):
                continue
            path = f"capabilities.{semantic_key}"
            try:
                capability = definition(semantic_key, raw_profile.semantic_version)
                validate_agent_schema(raw_profile.agent_input_schema, capability)
                connection = await self._connections.get(
                    tenant_id,
                    raw_profile.execution.connection_id,
                )
                if connection is None:
                    raise CapabilityValidationError(
                        "connection_not_found",
                        "Connection does not belong to tenant",
                        "execution.connection_id",
                    )
                if connection.status is not IntegrationConnectionStatus.ACTIVE:
                    raise CapabilityValidationError(
                        "connection_disabled",
                        "Connection must be active",
                        "execution.connection_id",
                    )
                if connection.provider is not IntegrationProvider.GOOGLE_SHEETS:
                    raise CapabilityValidationError(
                        "connection_provider_mismatch",
                        "Connection provider does not match plan type",
                        "execution.connection_id",
                    )
                for index, fixture in enumerate(raw_profile.validation_fixtures):
                    validate_agent_input(raw_profile.agent_input_schema, fixture)
                    canonical = validate_business_input(
                        normalize_input(raw_profile.agent_input_schema, fixture),
                        config.localization.timezone,
                        enforce_not_past=False,
                    )
                    compile_plan(
                        raw_profile,
                        canonical,
                        operation_id=UUID("00000000-0000-0000-0000-000000000001"),
                        call_id=UUID("00000000-0000-0000-0000-000000000002"),
                        tool_call_id=f"publication-fixture-{index}",
                        credential_ref=connection.credential_ref,
                    )
            except CapabilityValidationError as error:
                errors.append(
                    ValidationIssue(
                        path=f"{path}.{error.path}".rstrip("."),
                        code=error.code,
                        message=error.message,
                    )
                )
        return errors
