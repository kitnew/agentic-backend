from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from control_plane.domain.components import ComponentAddress, ComponentDefinition
from control_plane.domain.components.errors import (
    ActiveRevisionConflict,
    ComponentNotFound,
    DraftNotFound,
    DraftVersionConflict,
    RevisionNotFound,
    UnpublishedDraftConflict,
    UnsupportedSchemaVersion,
)

from .models import ConfigurationComponent as ComponentRow
from .models import ConfigurationComponentDraft as DraftRow
from .models import ConfigurationComponentRevision as RevisionRow


class SqlAlchemyComponentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    def _component(self, address: ComponentAddress):
        return select(ComponentRow).where(
            ComponentRow.kind == str(address.kind),
            ComponentRow.scope_type == address.scope.type.value,
            ComponentRow.scope_key.is_(None)
            if address.scope.key is None
            else ComponentRow.scope_key == address.scope.key,
        )

    async def _locked_component(
        self, session: AsyncSession, address: ComponentAddress
    ) -> ComponentRow:
        row = await session.scalar(self._component(address).with_for_update())
        if row is None:
            raise ComponentNotFound(str(address))
        return row

    async def save_draft(
        self,
        address: ComponentAddress,
        value: Mapping[str, Any],
        schema_version: int,
        expected_draft_version: int | None,
        expected_active_revision_id: UUID | None,
        actor: str,
    ) -> DraftRow:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(ComponentRow)
                .values(
                    kind=str(address.kind),
                    scope_type=address.scope.type.value,
                    scope_key=address.scope.key,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        ComponentRow.kind,
                        ComponentRow.scope_type,
                        ComponentRow.scope_key,
                    ]
                )
            )
            component = await self._locked_component(session, address)
            if component.active_revision_id != expected_active_revision_id:
                raise ActiveRevisionConflict("active revision changed")
            draft = await session.get(DraftRow, component.id, with_for_update=True)
            if draft is None:
                if expected_draft_version is not None:
                    raise DraftVersionConflict("draft does not exist")
                draft = DraftRow(
                    component_id=component.id,
                    schema_version=schema_version,
                    value=dict(value),
                    version=1,
                    based_on_revision_id=component.active_revision_id,
                    updated_by=actor,
                )
                session.add(draft)
            else:
                if draft.version != expected_draft_version:
                    raise DraftVersionConflict(
                        f"expected draft version {expected_draft_version}, current {draft.version}"
                    )
                draft.schema_version = schema_version
                draft.value = dict(value)
                draft.version += 1
                draft.updated_by = actor
                draft.updated_at = func.now()
            component.updated_at = func.now()
            await session.flush()
            await session.refresh(draft)
            return draft

    async def discard_draft(
        self, address: ComponentAddress, expected_draft_version: int
    ) -> None:
        async with self._sessions.begin() as session:
            component = await self._locked_component(session, address)
            draft = await session.get(DraftRow, component.id, with_for_update=True)
            if draft is None:
                raise DraftNotFound(str(address))
            if draft.version != expected_draft_version:
                raise DraftVersionConflict("draft version changed")
            await session.delete(draft)
            component.updated_at = func.now()

    async def publish_draft(
        self,
        address: ComponentAddress,
        expected_draft_version: int,
        actor: str,
        definition: ComponentDefinition[Any],
    ) -> RevisionRow:
        async with self._sessions.begin() as session:
            component = await self._locked_component(session, address)
            draft = await session.get(DraftRow, component.id, with_for_update=True)
            if draft is None:
                raise DraftVersionConflict("draft was already published or discarded")
            if draft.version != expected_draft_version:
                raise DraftVersionConflict("draft version changed")
            self._validate(draft.schema_version, draft.value, definition)
            current_number = await session.scalar(
                select(func.coalesce(func.max(RevisionRow.revision_number), 0)).where(
                    RevisionRow.component_id == component.id
                )
            )
            assert current_number is not None
            number = current_number + 1
            revision = RevisionRow(
                component_id=component.id,
                revision_number=number,
                schema_version=draft.schema_version,
                value=draft.value,
                based_on_revision_id=draft.based_on_revision_id,
                restored_from_revision_id=None,
                created_by=actor,
            )
            session.add(revision)
            await session.flush()
            component.active_revision_id = revision.id
            component.updated_at = func.now()
            await session.delete(draft)
            await session.flush()
            await session.refresh(revision)
            return revision

    async def rollback(
        self,
        address: ComponentAddress,
        revision_number: int,
        actor: str,
        definition: ComponentDefinition[Any],
    ) -> RevisionRow:
        async with self._sessions.begin() as session:
            component = await self._locked_component(session, address)
            if await session.get(DraftRow, component.id) is not None:
                raise UnpublishedDraftConflict("discard or publish the draft first")
            if component.active_revision_id is None:
                raise RevisionNotFound("active revision not found")
            target = await session.scalar(
                select(RevisionRow).where(
                    RevisionRow.component_id == component.id,
                    RevisionRow.revision_number == revision_number,
                )
            )
            if target is None:
                raise RevisionNotFound(str(revision_number))
            self._validate(target.schema_version, target.value, definition)
            current_number = await session.scalar(
                select(func.max(RevisionRow.revision_number)).where(
                    RevisionRow.component_id == component.id
                )
            )
            assert current_number is not None
            number = current_number + 1
            revision = RevisionRow(
                component_id=component.id,
                revision_number=number,
                schema_version=target.schema_version,
                value=target.value,
                based_on_revision_id=component.active_revision_id,
                restored_from_revision_id=target.id,
                created_by=actor,
            )
            session.add(revision)
            await session.flush()
            component.active_revision_id = revision.id
            component.updated_at = func.now()
            await session.flush()
            await session.refresh(revision)
            return revision

    def _validate(
        self, schema_version: int, value: object, definition: ComponentDefinition[Any]
    ) -> None:
        if schema_version != definition.current_schema_version:
            raise UnsupportedSchemaVersion(
                f"expected {definition.current_schema_version}, got {schema_version}"
            )
        definition.deserialize(value)

    async def _component_id(
        self, session: AsyncSession, address: ComponentAddress
    ) -> UUID | None:
        return await session.scalar(
            self._component(address).with_only_columns(ComponentRow.id)
        )

    async def get_component(
        self, address: ComponentAddress
    ) -> tuple[bool, DraftRow | None, RevisionRow | None]:
        async with self._sessions() as session:
            component = await session.scalar(self._component(address))
            if component is None:
                return False, None, None
            draft = await session.get(DraftRow, component.id)
            active = (
                await session.get(RevisionRow, component.active_revision_id)
                if component.active_revision_id
                else None
            )
            return True, draft, active

    async def get_draft(self, address: ComponentAddress) -> DraftRow | None:
        async with self._sessions() as session:
            component_id = await self._component_id(session, address)
            return await session.get(DraftRow, component_id) if component_id else None

    async def get_active(self, address: ComponentAddress) -> RevisionRow | None:
        async with self._sessions() as session:
            component = await session.scalar(self._component(address))
            return (
                await session.get(RevisionRow, component.active_revision_id)
                if component and component.active_revision_id
                else None
            )

    async def get_revision(
        self, address: ComponentAddress, revision_number: int
    ) -> RevisionRow | None:
        async with self._sessions() as session:
            component_id = await self._component_id(session, address)
            return (
                await session.scalar(
                    select(RevisionRow).where(
                        RevisionRow.component_id == component_id,
                        RevisionRow.revision_number == revision_number,
                    )
                )
                if component_id
                else None
            )

    async def list_revisions(
        self, address: ComponentAddress, limit: int
    ) -> Sequence[RevisionRow]:
        async with self._sessions() as session:
            component_id = await self._component_id(session, address)
            if component_id is None:
                return []
            return (
                await session.scalars(
                    select(RevisionRow)
                    .where(RevisionRow.component_id == component_id)
                    .order_by(RevisionRow.revision_number.desc())
                    .limit(limit)
                )
            ).all()
