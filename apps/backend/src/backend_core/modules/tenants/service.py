from uuid import UUID

from sqlalchemy.exc import IntegrityError

from backend_core.modules.tenants.errors import (
    TenantNotFoundError,
    TenantSlugConflictError,
)
from backend_core.modules.tenants.models import Tenant
from backend_core.modules.tenants.repository import TenantRepository
from backend_core.modules.tenants.schemas import TenantCreate


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
