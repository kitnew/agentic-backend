from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from backend_core.modules.tenants.errors import (
    ActiveConfigNotFoundError,
    ActiveDraftExistsError,
    ConfigRevisionImmutableError,
    ConfigRevisionNotCloneableError,
    ConfigRevisionNotFoundError,
    InvalidTenantConfigError,
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    Tenant,
    TenantConfigRevision,
)
from backend_core.modules.tenants.repository import (
    ConfigRevisionRepository,
    TenantRepository,
)
from backend_core.modules.tenants.schemas import (
    ConfigRevisionClone,
    ConfigRevisionCreate,
    ConfigRevisionUpdate,
    TenantConfigV1,
    TenantCreate,
)


class TenantService:
    def __init__(self, repository: TenantRepository) -> None:
        self._repository = repository

    async def create(self, data: TenantCreate) -> Tenant:
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


class ConfigRevisionService:
    def __init__(
        self,
        tenants: TenantRepository,
        revisions: ConfigRevisionRepository,
    ) -> None:
        self._tenants = tenants
        self._revisions = revisions

    async def create_draft(
        self,
        tenant_id: UUID,
        data: ConfigRevisionCreate,
    ) -> TenantConfigRevision:
        await self._tenant_for_update(tenant_id)
        await self._ensure_no_draft(tenant_id)
        revision = TenantConfigRevision(
            tenant_id=tenant_id,
            revision_number=await self._revisions.next_revision_number(tenant_id),
            **data.model_dump(),
        )
        try:
            return await self._revisions.add(revision)
        except IntegrityError as error:
            raise ActiveDraftExistsError from error

    async def clone(
        self,
        tenant_id: UUID,
        revision_id: UUID,
        data: ConfigRevisionClone,
    ) -> TenantConfigRevision:
        await self._tenant_for_update(tenant_id)
        await self._ensure_no_draft(tenant_id)
        source = await self._revision(tenant_id, revision_id)
        if source.status is ConfigRevisionStatus.DRAFT:
            raise ConfigRevisionNotCloneableError

        revision = TenantConfigRevision(
            tenant_id=tenant_id,
            revision_number=await self._revisions.next_revision_number(tenant_id),
            schema_version=source.schema_version,
            config=deepcopy(source.config),
            created_by=data.created_by,
            comment=data.comment,
        )
        try:
            return await self._revisions.add(revision)
        except IntegrityError as error:
            raise ActiveDraftExistsError from error

    async def update(
        self,
        tenant_id: UUID,
        revision_id: UUID,
        data: ConfigRevisionUpdate,
    ) -> TenantConfigRevision:
        revision = await self._revision_for_update(tenant_id, revision_id)
        if revision.status is not ConfigRevisionStatus.DRAFT:
            raise ConfigRevisionImmutableError

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(revision, field, value)
        await self._revisions.flush()
        return revision

    async def validate(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision:
        revision = await self._revision(tenant_id, revision_id)
        self._validate_config(revision)
        return revision

    async def publish(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision:
        tenant = await self._tenant_for_update(tenant_id)
        revision = await self._revision_for_update(tenant_id, revision_id)
        if revision.status is not ConfigRevisionStatus.DRAFT:
            raise ConfigRevisionImmutableError
        self._validate_config(revision)

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

    async def list(self, tenant_id: UUID) -> list[TenantConfigRevision]:
        if await self._tenants.get(tenant_id) is None:
            raise TenantNotFoundError
        return await self._revisions.list(tenant_id)

    async def get_active(
        self,
        tenant_id: UUID,
    ) -> tuple[TenantConfigRevision, TenantConfigV1]:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        if tenant.active_config_revision_id is None:
            raise ActiveConfigNotFoundError

        revision = await self._revision(
            tenant_id,
            tenant.active_config_revision_id,
        )
        if (
            revision.status is not ConfigRevisionStatus.PUBLISHED
            or revision.published_at is None
        ):
            raise ActiveConfigNotFoundError
        return revision, self._validate_config(revision)

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
    def _validate_config(revision: TenantConfigRevision) -> TenantConfigV1:
        if revision.schema_version != 1:
            raise InvalidTenantConfigError(
                [
                    {
                        "type": "literal_error",
                        "loc": ["schema_version"],
                        "msg": "only schema_version 1 is supported",
                    }
                ]
            )
        try:
            config = TenantConfigV1.model_validate(revision.config)
        except ValidationError as error:
            raise InvalidTenantConfigError(
                error.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            ) from error
        if config.schema_version != revision.schema_version:
            raise InvalidTenantConfigError(
                [
                    {
                        "type": "value_error",
                        "loc": ["config", "schema_version"],
                        "msg": "config and revision schema versions differ",
                    }
                ]
            )
        return config
