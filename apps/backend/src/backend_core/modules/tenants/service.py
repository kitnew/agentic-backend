from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

from contracts import TenantConfigV1
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

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
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    InboundRoute,
    Tenant,
    TenantConfigRevision,
)
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    InboundRouteRepository,
    TenantRepository,
)
from backend_core.modules.tenants.schemas import (
    CreateDraftRequest,
    CreateInboundRouteRequest,
    CreateTenantRequest,
    UpdateDraftRequest,
    UpdateInboundRouteRequest,
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


class ConfigUseCases:
    def __init__(
        self,
        tenants: TenantRepository,
        revisions: ConfigRevisionRepository,
    ) -> None:
        self._tenants = tenants
        self._revisions = revisions

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
        _, errors = self._validate_config(revision)
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
        _, errors = self._validate_config(revision)
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
    ) -> tuple[TenantConfigRevision, TenantConfigV1]:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        return await self._active_config(tenant)

    async def get_internal_active_config(
        self,
        tenant_id: UUID,
    ) -> tuple[TenantConfigRevision, TenantConfigV1]:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None or not tenant.is_available_in_runtime:
            raise TenantNotFoundError
        return await self._active_config(tenant)

    async def _active_config(
        self,
        tenant: Tenant,
    ) -> tuple[TenantConfigRevision, TenantConfigV1]:
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
        config, errors = self._validate_config(revision)
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

    @staticmethod
    def _validate_config(
        revision: TenantConfigRevision,
    ) -> tuple[TenantConfigV1 | None, list[ValidationIssue]]:
        if revision.schema_version != 1:
            return (
                None,
                [
                    ValidationIssue(
                        path="schema_version",
                        code="unsupported_schema_version",
                        message="Only schema_version 1 is supported",
                    )
                ],
            )
        try:
            config = TenantConfigV1.model_validate(revision.config)
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
        return config, []
