from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from control_plane.domain.components import ComponentAddress, ComponentDefinition


class StoredDraft(Protocol):
    schema_version: int
    value: Mapping[str, Any]
    version: int
    based_on_revision_id: UUID | None
    updated_at: datetime
    updated_by: str


class StoredRevision(Protocol):
    id: UUID
    revision_number: int
    schema_version: int
    value: Mapping[str, Any]
    based_on_revision_id: UUID | None
    restored_from_revision_id: UUID | None
    created_at: datetime
    created_by: str


class ComponentRepository(Protocol):
    async def get_component(
        self, address: ComponentAddress
    ) -> tuple[bool, StoredDraft | None, StoredRevision | None]: ...

    async def save_draft(
        self,
        address: ComponentAddress,
        value: Mapping[str, Any],
        schema_version: int,
        expected_draft_version: int | None,
        expected_active_revision_id: UUID | None,
        actor: str,
    ) -> StoredDraft: ...
    async def discard_draft(
        self, address: ComponentAddress, expected_draft_version: int
    ) -> None: ...
    async def publish_draft(
        self,
        address: ComponentAddress,
        expected_draft_version: int,
        actor: str,
        definition: ComponentDefinition[Any],
    ) -> StoredRevision: ...
    async def rollback(
        self,
        address: ComponentAddress,
        revision_number: int,
        actor: str,
        definition: ComponentDefinition[Any],
    ) -> StoredRevision: ...
    async def get_draft(self, address: ComponentAddress) -> StoredDraft | None: ...
    async def get_active(self, address: ComponentAddress) -> StoredRevision | None: ...
    async def get_revision(
        self, address: ComponentAddress, revision_number: int
    ) -> StoredRevision | None: ...
    async def list_revisions(
        self, address: ComponentAddress, limit: int
    ) -> Sequence[StoredRevision]: ...
