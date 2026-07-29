from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    InboundRoute,
    Tenant,
    TenantConfigRevision,
    TenantStatus,
)


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
        tenants = await self._session.scalars(
            select(Tenant)
            .order_by(Tenant.created_at, Tenant.id)
            .offset(offset)
            .limit(limit)
        )
        return list(tenants)


class InboundRouteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, route: InboundRoute) -> InboundRoute:
        self._session.add(route)
        await self._session.flush()
        return route

    async def get(self, tenant_id: UUID, route_id: UUID) -> InboundRoute | None:
        return await self._session.scalar(
            select(InboundRoute).where(
                InboundRoute.tenant_id == tenant_id,
                InboundRoute.id == route_id,
            )
        )

    async def list(self, tenant_id: UUID) -> list[InboundRoute]:
        routes = await self._session.scalars(
            select(InboundRoute)
            .where(InboundRoute.tenant_id == tenant_id)
            .order_by(InboundRoute.created_at, InboundRoute.id)
        )
        return list(routes)

    async def flush(self) -> None:
        await self._session.flush()

    async def refresh(self, route: InboundRoute) -> None:
        await self._session.refresh(route)

    async def resolve(
        self,
        normalized_did: str,
    ) -> tuple[Tenant, TenantConfigRevision] | None:
        row = (
            await self._session.execute(
                select(Tenant, TenantConfigRevision)
                .join(InboundRoute, InboundRoute.tenant_id == Tenant.id)
                .join(
                    TenantConfigRevision,
                    TenantConfigRevision.id == Tenant.active_config_revision_id,
                )
                .where(
                    InboundRoute.normalized_did == normalized_did,
                    InboundRoute.enabled.is_(True),
                    Tenant.status == TenantStatus.ACTIVE,
                    TenantConfigRevision.status == ConfigRevisionStatus.PUBLISHED,
                    TenantConfigRevision.published_at.is_not(None),
                )
            )
        ).one_or_none()
        return None if row is None else (row[0], row[1])


class ConfigRevisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, revision: TenantConfigRevision) -> TenantConfigRevision:
        self._session.add(revision)
        await self._session.flush()
        return revision

    async def flush(self) -> None:
        await self._session.flush()

    async def get(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision | None:
        return await self._session.scalar(
            select(TenantConfigRevision).where(
                TenantConfigRevision.tenant_id == tenant_id,
                TenantConfigRevision.id == revision_id,
            )
        )

    async def get_for_update(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> TenantConfigRevision | None:
        return await self._session.scalar(
            select(TenantConfigRevision)
            .where(
                TenantConfigRevision.tenant_id == tenant_id,
                TenantConfigRevision.id == revision_id,
            )
            .with_for_update()
        )

    async def get_draft(self, tenant_id: UUID) -> TenantConfigRevision | None:
        return await self._session.scalar(
            select(TenantConfigRevision).where(
                TenantConfigRevision.tenant_id == tenant_id,
                TenantConfigRevision.status == ConfigRevisionStatus.DRAFT,
            )
        )

    async def next_revision_number(self, tenant_id: UUID) -> int:
        latest = await self._session.scalar(
            select(func.max(TenantConfigRevision.revision_number)).where(
                TenantConfigRevision.tenant_id == tenant_id
            )
        )
        return (latest or 0) + 1

    async def list(self, tenant_id: UUID) -> list[TenantConfigRevision]:
        revisions = await self._session.scalars(
            select(TenantConfigRevision)
            .where(TenantConfigRevision.tenant_id == tenant_id)
            .order_by(TenantConfigRevision.revision_number)
        )
        return list(revisions)
