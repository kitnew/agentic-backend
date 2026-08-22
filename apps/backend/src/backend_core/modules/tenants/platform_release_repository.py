from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.tenants.platform_release_models import (
    PlatformControl,
    PlatformProfilePromptComponentRevision,
    PlatformProfilePromptDraft,
    PlatformRelease,
    PlatformReleaseProfilePrompt,
    PlatformRuntimeComponentRevision,
    PlatformRuntimeDraft,
    PlatformSystemPromptComponentRevision,
    PlatformSystemPromptDraft,
)


class PlatformReleaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def control_for_update(self) -> PlatformControl:
        control = await self._session.scalar(
            select(PlatformControl).where(PlatformControl.id == 1).with_for_update()
        )
        if control is None:
            control = PlatformControl()
            self._session.add(control)
            await self._session.flush()
        return control

    async def active_release(self) -> PlatformRelease | None:
        return await self._session.scalar(
            select(PlatformRelease)
            .join(PlatformControl, PlatformControl.active_release_id == PlatformRelease.id)
            .where(PlatformControl.id == 1)
        )

    async def runtime_draft_for_update(self) -> PlatformRuntimeDraft | None:
        return await self._session.scalar(
            select(PlatformRuntimeDraft)
            .where(PlatformRuntimeDraft.id == 1)
            .with_for_update()
        )

    async def runtime_draft(self) -> PlatformRuntimeDraft | None:
        return await self._session.get(PlatformRuntimeDraft, 1)

    async def system_prompt_draft_for_update(self) -> PlatformSystemPromptDraft | None:
        return await self._session.scalar(
            select(PlatformSystemPromptDraft)
            .where(PlatformSystemPromptDraft.id == 1)
            .with_for_update()
        )

    async def system_prompt_draft(self) -> PlatformSystemPromptDraft | None:
        return await self._session.get(PlatformSystemPromptDraft, 1)

    async def profile_drafts_for_update(self) -> list[PlatformProfilePromptDraft]:
        return list(
            (
                await self._session.scalars(
                    select(PlatformProfilePromptDraft).with_for_update()
                )
            ).all()
        )

    async def profile_drafts(self) -> list[PlatformProfilePromptDraft]:
        return list((await self._session.scalars(select(PlatformProfilePromptDraft))).all())

    async def runtime_revision(
        self, revision_id: UUID
    ) -> PlatformRuntimeComponentRevision | None:
        return await self._session.get(PlatformRuntimeComponentRevision, revision_id)

    async def system_prompt_revision(
        self, revision_id: UUID
    ) -> PlatformSystemPromptComponentRevision | None:
        return await self._session.get(PlatformSystemPromptComponentRevision, revision_id)

    async def profile_revision(
        self, revision_id: UUID
    ) -> PlatformProfilePromptComponentRevision | None:
        return await self._session.get(PlatformProfilePromptComponentRevision, revision_id)

    async def profile_revision_for_release(
        self, release_id: UUID, profile: str
    ) -> PlatformProfilePromptComponentRevision | None:
        return await self._session.scalar(
            select(PlatformProfilePromptComponentRevision)
            .join(
                PlatformReleaseProfilePrompt,
                PlatformReleaseProfilePrompt.profile_prompt_revision_id
                == PlatformProfilePromptComponentRevision.id,
            )
            .where(
                PlatformReleaseProfilePrompt.release_id == release_id,
                PlatformReleaseProfilePrompt.profile == profile,
            )
        )

    async def release_profiles(
        self, release_id: UUID
    ) -> list[PlatformReleaseProfilePrompt]:
        return list(
            (
                await self._session.scalars(
                    select(PlatformReleaseProfilePrompt).where(
                        PlatformReleaseProfilePrompt.release_id == release_id
                    )
                )
            ).all()
        )

    async def next_number(self, model: type[Any], *, profile: str | None = None) -> int:
        statement = select(func.max(model.revision_number))
        if profile is not None:
            statement = statement.where(model.profile == profile)
        return (await self._session.scalar(statement) or 0) + 1

    async def next_release_number(self) -> int:
        return (await self._session.scalar(select(func.max(PlatformRelease.release_number))) or 0) + 1

    async def add(self, value: object) -> None:
        self._session.add(value)
        await self._session.flush()

    async def delete(self, value: object) -> None:
        await self._session.delete(value)
