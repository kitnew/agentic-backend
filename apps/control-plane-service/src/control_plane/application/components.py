from typing import Any
from uuid import UUID

from control_plane.application.ports.repositories import (
    ComponentRepository,
    StoredDraft,
    StoredRevision,
)
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDraft,
    ComponentRegistry,
    ComponentRevision,
    ComponentSnapshot,
    ComponentState,
)
from control_plane.domain.components.errors import (
    ComponentNotFound,
    DraftNotFound,
    RevisionNotFound,
    UnsupportedSchemaVersion,
)


class ComponentService:
    def __init__(
        self, registry: ComponentRegistry, repository: ComponentRepository
    ) -> None:
        self._registry = registry
        self._repository = repository

    async def save_draft(
        self,
        address: ComponentAddress,
        raw_value: object,
        schema_version: int,
        expected_draft_version: int | None,
        expected_active_revision_id: UUID | None,
        actor: str,
    ) -> ComponentDraft[Any]:
        definition = self._definition(address, schema_version)
        typed = definition.deserialize(raw_value)
        row = await self._repository.save_draft(
            address,
            definition.serialize(typed),
            schema_version,
            expected_draft_version,
            expected_active_revision_id,
            actor,
        )
        return self._draft(address, row)

    async def discard_draft(
        self, address: ComponentAddress, expected_draft_version: int
    ) -> None:
        self._registry.resolve(address)
        await self._repository.discard_draft(address, expected_draft_version)

    async def publish_draft(
        self, address: ComponentAddress, expected_draft_version: int, actor: str
    ) -> ComponentRevision[Any]:
        definition = self._registry.resolve(address)
        return self._revision(
            address,
            await self._repository.publish_draft(
                address, expected_draft_version, actor, definition
            ),
        )

    async def rollback(
        self, address: ComponentAddress, revision_number: int, actor: str
    ) -> ComponentRevision[Any]:
        definition = self._registry.resolve(address)
        return self._revision(
            address,
            await self._repository.rollback(
                address, revision_number, actor, definition
            ),
        )

    async def get_component(self, address: ComponentAddress) -> ComponentSnapshot[Any]:
        self._registry.resolve(address)
        exists, draft, active = await self._repository.get_component(address)
        if not exists:
            raise ComponentNotFound(str(address))
        return ComponentSnapshot(
            address,
            ComponentState.derive(
                has_active=active is not None, has_draft=draft is not None
            ),
            self._revision(address, active) if active else None,
            self._draft(address, draft) if draft else None,
        )

    async def get_draft(self, address: ComponentAddress) -> ComponentDraft[Any]:
        self._registry.resolve(address)
        row = await self._repository.get_draft(address)
        if row is None:
            raise DraftNotFound(str(address))
        return self._draft(address, row)

    async def get_active(self, address: ComponentAddress) -> ComponentRevision[Any]:
        self._registry.resolve(address)
        row = await self._repository.get_active(address)
        if row is None:
            raise RevisionNotFound("active revision not found")
        return self._revision(address, row)

    async def get_revision(
        self, address: ComponentAddress, revision_number: int
    ) -> ComponentRevision[Any]:
        self._registry.resolve(address)
        row = await self._repository.get_revision(address, revision_number)
        if row is None:
            raise RevisionNotFound(str(revision_number))
        return self._revision(address, row)

    async def list_revisions(
        self, address: ComponentAddress, limit: int = 100
    ) -> list[ComponentRevision[Any]]:
        self._registry.resolve(address)
        exists, _, _ = await self._repository.get_component(address)
        if not exists:
            raise ComponentNotFound(str(address))
        return [
            self._revision(address, row)
            for row in await self._repository.list_revisions(address, limit)
        ]

    def _definition(self, address: ComponentAddress, schema_version: int):
        definition = self._registry.resolve(address)
        if schema_version != definition.current_schema_version:
            raise UnsupportedSchemaVersion(
                f"expected {definition.current_schema_version}, got {schema_version}"
            )
        return definition

    def _draft(
        self, address: ComponentAddress, row: StoredDraft
    ) -> ComponentDraft[Any]:
        definition = self._definition(address, row.schema_version)
        return ComponentDraft(
            address,
            definition.deserialize(row.value),
            row.schema_version,
            row.version,
            row.based_on_revision_id,
            row.updated_at,
            row.updated_by,
        )

    def _revision(
        self, address: ComponentAddress, row: StoredRevision
    ) -> ComponentRevision[Any]:
        definition = self._definition(address, row.schema_version)
        return ComponentRevision(
            row.id,
            address,
            row.revision_number,
            definition.deserialize(row.value),
            row.schema_version,
            row.based_on_revision_id,
            row.restored_from_revision_id,
            row.created_at,
            row.created_by,
        )
