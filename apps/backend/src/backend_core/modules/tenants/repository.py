from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.tenants.models import (
    ConfigRevisionStatus,
    InboundRoute,
    KnowledgeBase,
    ProfilePrompt,
    PromptBundleRevision,
    PromptBundleRevisionStatus,
    PromptRevisionStatus,
    PromptSet,
    SystemPrompt,
    Tenant,
    TenantConfigRevision,
    TenantPrompt,
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
        *,
        lock_tenant: bool = False,
    ) -> tuple[Tenant, TenantConfigRevision] | None:
        query = (
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
        if lock_tenant:
            query = query.with_for_update(of=Tenant)
        row = (await self._session.execute(query)).one_or_none()
        return None if row is None else (row[0], row[1])


class PromptBundleRevisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, revision: PromptBundleRevision) -> PromptBundleRevision:
        self._session.add(revision)
        await self._session.flush()
        return revision

    async def flush(self) -> None:
        await self._session.flush()

    async def get(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> PromptBundleRevision | None:
        return await self._session.scalar(
            select(PromptBundleRevision).where(
                PromptBundleRevision.tenant_id == tenant_id,
                PromptBundleRevision.id == revision_id,
            )
        )

    async def get_for_update(
        self,
        tenant_id: UUID,
        revision_id: UUID,
    ) -> PromptBundleRevision | None:
        return await self._session.scalar(
            select(PromptBundleRevision)
            .where(
                PromptBundleRevision.tenant_id == tenant_id,
                PromptBundleRevision.id == revision_id,
            )
            .with_for_update()
        )

    async def get_draft(self, tenant_id: UUID) -> PromptBundleRevision | None:
        return await self._session.scalar(
            select(PromptBundleRevision).where(
                PromptBundleRevision.tenant_id == tenant_id,
                PromptBundleRevision.status == PromptBundleRevisionStatus.DRAFT,
            )
        )

    async def next_revision_number(self, tenant_id: UUID) -> int:
        latest = await self._session.scalar(
            select(func.max(PromptBundleRevision.revision_number)).where(
                PromptBundleRevision.tenant_id == tenant_id
            )
        )
        return (latest or 0) + 1

    async def list(self, tenant_id: UUID) -> list[PromptBundleRevision]:
        revisions = await self._session.scalars(
            select(PromptBundleRevision)
            .where(PromptBundleRevision.tenant_id == tenant_id)
            .order_by(PromptBundleRevision.revision_number)
        )
        return list(revisions)


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


class PromptCompositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def system_prompt(self, key: str) -> SystemPrompt | None:
        return await self._session.scalar(
            select(SystemPrompt).where(SystemPrompt.key == key)
        )

    async def profile_prompt(self, key: str) -> ProfilePrompt | None:
        return await self._session.scalar(
            select(ProfilePrompt).where(ProfilePrompt.key == key)
        )

    async def profile_prompt_by_id(self, prompt_id: UUID) -> ProfilePrompt | None:
        return await self._session.get(ProfilePrompt, prompt_id)

    async def list_profile_prompts(self) -> list[ProfilePrompt]:
        return list(
            await self._session.scalars(select(ProfilePrompt).order_by(ProfilePrompt.key))
        )

    async def tenant_prompt(self, tenant_id: UUID) -> TenantPrompt | None:
        return await self._session.scalar(
            select(TenantPrompt).where(TenantPrompt.tenant_id == tenant_id)
        )

    async def knowledge_base(self, tenant_id: UUID) -> KnowledgeBase | None:
        return await self._session.scalar(
            select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id)
        )

    async def prompt_set(self, tenant_id: UUID) -> PromptSet | None:
        return await self._session.scalar(
            select(PromptSet).where(PromptSet.tenant_id == tenant_id)
        )

    async def add(self, value: Any) -> Any:
        self._session.add(value)
        await self._session.flush()
        return value

    async def revision(
        self,
        revision_type: type[Any],
        revision_id: UUID,
        *,
        tenant_id: UUID | None = None,
        lock: bool = False,
    ) -> Any | None:
        query = select(revision_type).where(revision_type.id == revision_id)
        if tenant_id is not None:
            query = query.where(revision_type.tenant_id == tenant_id)
        if lock:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def revision_by_parent(
        self,
        revision_type: type[Any],
        parent_field: str,
        parent_id: UUID,
        *,
        status: PromptRevisionStatus | None = None,
    ) -> list[Any]:
        query = select(revision_type).where(
            getattr(revision_type, parent_field) == parent_id
        )
        if status is not None:
            query = query.where(revision_type.status == status)
        query = query.order_by(revision_type.revision_number)
        return list(await self._session.scalars(query))

    async def next_revision_number(
        self,
        revision_type: type[Any],
        parent_field: str,
        parent_id: UUID,
    ) -> int:
        latest = await self._session.scalar(
            select(func.max(revision_type.revision_number)).where(
                getattr(revision_type, parent_field) == parent_id
            )
        )
        return (latest or 0) + 1

    async def flush(self) -> None:
        await self._session.flush()
