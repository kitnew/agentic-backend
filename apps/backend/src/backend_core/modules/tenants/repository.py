from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.tenants.models import PlatformTelephony, Tenant
from backend_core.modules.tenants.release_models import TenantTelephonyProvisioning


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant: Tenant) -> Tenant:
        self._session.add(tenant)
        await self._session.flush()
        return tenant

    async def get(self, tenant_id: UUID) -> Tenant | None:
        return await self._session.get(Tenant, tenant_id)

    async def get_for_update(self, tenant_id: UUID) -> Tenant | None:
        return await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )

    async def get_by_slug(self, slug: str) -> Tenant | None:
        return await self._session.scalar(select(Tenant).where(Tenant.slug == slug))

    async def list(self, *, offset: int, limit: int) -> list[Tenant]:
        return list(
            await self._session.scalars(
                select(Tenant)
                .order_by(Tenant.created_at, Tenant.id)
                .offset(offset)
                .limit(limit)
            )
        )


class TelephonyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def platform(self, *, for_update: bool = False) -> PlatformTelephony:
        query = select(PlatformTelephony).where(PlatformTelephony.id == 1)
        if for_update:
            query = query.with_for_update()
        state = await self._session.scalar(query)
        if state is None:
            state = PlatformTelephony(id=1)
            self._session.add(state)
            await self._session.flush()
        return state

    async def provisioning(self) -> list[TenantTelephonyProvisioning]:
        return list(await self._session.scalars(select(TenantTelephonyProvisioning)))

    async def provisioning_for(self, tenant_id: UUID, assignment_id: UUID | None = None) -> TenantTelephonyProvisioning | None:
        if assignment_id is None:
            return await self._session.scalar(select(TenantTelephonyProvisioning).where(TenantTelephonyProvisioning.tenant_id == tenant_id))
        return await self._session.scalar(
            select(TenantTelephonyProvisioning).where(
                TenantTelephonyProvisioning.tenant_id == tenant_id,
                TenantTelephonyProvisioning.phone_assignment_id == assignment_id,
            )
        )

    async def flush(self) -> None:
        await self._session.flush()

    async def add(self, value: TenantTelephonyProvisioning) -> None:
        self._session.add(value)
        await self._session.flush()
