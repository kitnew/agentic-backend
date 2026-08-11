from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.runtime.voice.models import (
    PlatformRuntime,
    PlatformRuntimeRevision,
    RuntimeRevisionStatus,
    TenantRuntime,
    TenantRuntimeRevision,
    VoiceRuntime,
    VoiceRuntimeRevision,
)


class VoiceRuntimeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def flush(self) -> None:
        await self._session.flush()

    async def add(self, value: object) -> None:
        self._session.add(value)
        await self._session.flush()

    async def platform(self, *, lock: bool = False) -> PlatformRuntime | None:
        query = select(PlatformRuntime).where(PlatformRuntime.key == "default")
        if lock:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def platform_revision(
        self, revision_id: UUID, *, lock: bool = False
    ) -> PlatformRuntimeRevision | None:
        query = select(PlatformRuntimeRevision).where(
            PlatformRuntimeRevision.id == revision_id
        )
        if lock:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def platform_revisions(self) -> list[PlatformRuntimeRevision]:
        return list(
            await self._session.scalars(
                select(PlatformRuntimeRevision).order_by(
                    PlatformRuntimeRevision.revision_number
                )
            )
        )

    async def platform_draft(self, platform_id: UUID) -> PlatformRuntimeRevision | None:
        return await self._session.scalar(
            select(PlatformRuntimeRevision).where(
                PlatformRuntimeRevision.platform_runtime_id == platform_id,
                PlatformRuntimeRevision.status == RuntimeRevisionStatus.DRAFT,
            )
        )

    async def published_platform_revision(
        self, platform_id: UUID
    ) -> PlatformRuntimeRevision | None:
        return await self._session.scalar(
            select(PlatformRuntimeRevision)
            .where(
                PlatformRuntimeRevision.platform_runtime_id == platform_id,
                PlatformRuntimeRevision.status == RuntimeRevisionStatus.PUBLISHED,
            )
            .order_by(PlatformRuntimeRevision.revision_number.desc())
            .limit(1)
        )

    async def next_platform_revision_number(self, platform_id: UUID) -> int:
        latest = await self._session.scalar(
            select(func.max(PlatformRuntimeRevision.revision_number)).where(
                PlatformRuntimeRevision.platform_runtime_id == platform_id
            )
        )
        return (latest or 0) + 1

    async def tenant_runtime(
        self, tenant_id: UUID, *, lock: bool = False
    ) -> TenantRuntime | None:
        query = select(TenantRuntime).where(TenantRuntime.tenant_id == tenant_id)
        if lock:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def tenant_revision(
        self, tenant_id: UUID, revision_id: UUID, *, lock: bool = False
    ) -> TenantRuntimeRevision | None:
        query = select(TenantRuntimeRevision).where(
            TenantRuntimeRevision.tenant_id == tenant_id,
            TenantRuntimeRevision.id == revision_id,
        )
        if lock:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def tenant_revisions(self, tenant_id: UUID) -> list[TenantRuntimeRevision]:
        return list(
            await self._session.scalars(
                select(TenantRuntimeRevision)
                .where(TenantRuntimeRevision.tenant_id == tenant_id)
                .order_by(TenantRuntimeRevision.revision_number)
            )
        )

    async def tenant_draft(
        self, tenant_runtime_id: UUID
    ) -> TenantRuntimeRevision | None:
        return await self._session.scalar(
            select(TenantRuntimeRevision).where(
                TenantRuntimeRevision.tenant_runtime_id == tenant_runtime_id,
                TenantRuntimeRevision.status == RuntimeRevisionStatus.DRAFT,
            )
        )

    async def published_tenant_revision(
        self, tenant_runtime_id: UUID
    ) -> TenantRuntimeRevision | None:
        return await self._session.scalar(
            select(TenantRuntimeRevision)
            .where(
                TenantRuntimeRevision.tenant_runtime_id == tenant_runtime_id,
                TenantRuntimeRevision.status == RuntimeRevisionStatus.PUBLISHED,
            )
            .order_by(TenantRuntimeRevision.revision_number.desc())
            .limit(1)
        )

    async def next_tenant_revision_number(self, tenant_runtime_id: UUID) -> int:
        latest = await self._session.scalar(
            select(func.max(TenantRuntimeRevision.revision_number)).where(
                TenantRuntimeRevision.tenant_runtime_id == tenant_runtime_id
            )
        )
        return (latest or 0) + 1

    async def voice_runtime(
        self, tenant_id: UUID, *, lock: bool = False
    ) -> VoiceRuntime | None:
        query = select(VoiceRuntime).where(VoiceRuntime.tenant_id == tenant_id)
        if lock:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def voice_revision(
        self, tenant_id: UUID, revision_id: UUID, *, lock: bool = False
    ) -> VoiceRuntimeRevision | None:
        query = select(VoiceRuntimeRevision).where(
            VoiceRuntimeRevision.tenant_id == tenant_id,
            VoiceRuntimeRevision.id == revision_id,
        )
        if lock:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def voice_revisions(self, tenant_id: UUID) -> list[VoiceRuntimeRevision]:
        return list(
            await self._session.scalars(
                select(VoiceRuntimeRevision)
                .where(VoiceRuntimeRevision.tenant_id == tenant_id)
                .order_by(VoiceRuntimeRevision.revision_number)
            )
        )

    async def next_voice_revision_number(self, voice_runtime_id: UUID) -> int:
        latest = await self._session.scalar(
            select(func.max(VoiceRuntimeRevision.revision_number)).where(
                VoiceRuntimeRevision.voice_runtime_id == voice_runtime_id
            )
        )
        return (latest or 0) + 1
