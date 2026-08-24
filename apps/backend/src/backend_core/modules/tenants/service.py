from uuid import UUID

from sqlalchemy.exc import IntegrityError

from backend_core.modules.tenants.defaults import default_component_payloads
from backend_core.modules.tenants.errors import (
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.models import Tenant
from backend_core.modules.tenants.release_repository import (
    TenantReleaseRepository,
)
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.modules.tenants.schemas import CreateTenantRequest


class TenantService:
    def __init__(
        self, repository: TenantRepository, releases: TenantReleaseRepository
    ) -> None:
        self._repository = repository
        self._releases = releases

    async def create(self, data: CreateTenantRequest) -> Tenant:
        if await self._repository.get_by_slug(data.slug):
            raise TenantSlugConflictError
        try:
            tenant = await self._repository.add(Tenant(**data.model_dump()))
            for component, payload in default_component_payloads(
                data.display_name, data.business_type
            ).items():
                await self._releases.save_draft(
                    component=component,
                    tenant_id=tenant.id,
                    payload=payload,
                    expected_version=None,
                )
            return tenant
        except IntegrityError as error:
            raise TenantSlugConflictError from error

    async def get(self, tenant_id: UUID) -> Tenant:
        tenant = await self._repository.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError
        return tenant

    async def get_by_slug(self, slug: str) -> Tenant:
        tenant = await self._repository.get_by_slug(slug)
        if tenant is None:
            raise TenantNotFoundError
        return tenant

    async def list(self, *, offset: int, limit: int) -> list[Tenant]:
        return await self._repository.list(offset=offset, limit=limit)
