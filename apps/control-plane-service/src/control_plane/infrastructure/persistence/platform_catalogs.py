from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control_plane.domain.catalogs import CatalogStatus, InteractionMode, Profile

from .models import InteractionModeCatalogEntry, ProfileCatalogEntry
from .repository import SqlAlchemyComponentRepository


class SqlAlchemyPlatformRepository(SqlAlchemyComponentRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._session_instance = session

    async def get_profile(self, key: str, *, lock: bool = False) -> Profile | None:
        statement = select(ProfileCatalogEntry).where(ProfileCatalogEntry.key == key)
        row = await self._session_instance.scalar(
            statement.with_for_update() if lock else statement
        )
        return _profile(row) if row else None

    async def list_profiles(self, *, lock: bool = False) -> list[Profile]:
        statement = select(ProfileCatalogEntry).order_by(ProfileCatalogEntry.key)
        rows = (
            await self._session_instance.scalars(
                statement.with_for_update() if lock else statement
            )
        ).all()
        return [_profile(row) for row in rows]

    async def put_profile(
        self,
        key: str,
        name: str,
        description: str,
        status: CatalogStatus,
        actor: str,
    ) -> Profile:
        row = await self._session_instance.get(
            ProfileCatalogEntry, key, with_for_update=True
        )
        if row is None:
            row = ProfileCatalogEntry(
                key=key,
                name=name,
                description=description,
                status=status.value,
                generation=1,
                updated_by=actor,
            )
            self._session_instance.add(row)
        else:
            row.name = name
            row.description = description
            row.status = status.value
            row.generation += 1
            row.updated_at = datetime.now(UTC)
            row.updated_by = actor
        await self._session_instance.flush()
        await self._session_instance.refresh(row)
        return _profile(row)

    async def get_interaction_mode(
        self, key: str, *, lock: bool = False
    ) -> InteractionMode | None:
        statement = select(InteractionModeCatalogEntry).where(
            InteractionModeCatalogEntry.key == key
        )
        row = await self._session_instance.scalar(
            statement.with_for_update() if lock else statement
        )
        return _interaction_mode(row) if row else None

    async def list_interaction_modes(
        self, *, lock: bool = False
    ) -> list[InteractionMode]:
        statement = select(InteractionModeCatalogEntry).order_by(
            InteractionModeCatalogEntry.key
        )
        rows = (
            await self._session_instance.scalars(
                statement.with_for_update() if lock else statement
            )
        ).all()
        return [_interaction_mode(row) for row in rows]

    async def put_interaction_mode(
        self,
        key: str,
        name: str,
        description: str,
        status: CatalogStatus,
        actor: str,
    ) -> InteractionMode:
        row = await self._session_instance.get(
            InteractionModeCatalogEntry, key, with_for_update=True
        )
        if row is None:
            row = InteractionModeCatalogEntry(
                key=key,
                name=name,
                description=description,
                status=status.value,
                generation=1,
                updated_by=actor,
            )
            self._session_instance.add(row)
        else:
            row.name = name
            row.description = description
            row.status = status.value
            row.generation += 1
            row.updated_at = datetime.now(UTC)
            row.updated_by = actor
        await self._session_instance.flush()
        await self._session_instance.refresh(row)
        return _interaction_mode(row)


def _profile(row: ProfileCatalogEntry) -> Profile:
    return Profile(
        row.key,
        row.name,
        row.description,
        CatalogStatus(row.status),
        row.generation,
        row.created_at,
        row.updated_at,
    )


def _interaction_mode(row: InteractionModeCatalogEntry) -> InteractionMode:
    return InteractionMode(
        row.key,
        row.name,
        row.description,
        CatalogStatus(row.status),
        row.generation,
        row.created_at,
        row.updated_at,
    )
