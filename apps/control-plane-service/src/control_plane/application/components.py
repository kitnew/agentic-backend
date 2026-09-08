from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from control_plane.application.command_support import (
    IdempotencyKeyReused,
    request_fingerprint,
)
from control_plane.application.ports.repositories import (
    ComponentRepository,
    StoredDraft,
    StoredRevision,
)
from control_plane.application.ports.transactions import ComponentCommandScope
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
    ComponentDraft,
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

PUBLISH_OPERATION = "versioned_component.publish"
ROLLBACK_OPERATION = "versioned_component.rollback"


class ComponentService:
    def __init__(
        self,
        registry: ComponentDefinitionRegistry,
        repository: ComponentRepository,
        command_scope: ComponentCommandScope | None = None,
        validate_value: Callable[[ComponentAddress, object], Awaitable[None]]
        | None = None,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._command_scope = command_scope
        self._validate_value = validate_value

    def lifecycle(self, address: ComponentAddress) -> str | None:
        return cast(
            str | None,
            self._registry.resolve(address).metadata.get("lifecycle"),
        )

    async def save_draft(
        self,
        address: ComponentAddress,
        raw_value: object,
        expected_draft_version: int | None,
        expected_active_revision_id: UUID | None,
        actor: str,
    ) -> ComponentDraft[Any]:
        definition = self._registry.resolve(address)
        typed = definition.deserialize(raw_value)
        if self._validate_value is not None:
            await self._validate_value(address, typed)
        arguments = (
            address,
            definition.serialize(typed),
            definition.schema_version,
            expected_draft_version,
            expected_active_revision_id,
            actor,
        )
        if self._command_scope is None:
            row = await self._repository.save_draft(*arguments)
        else:
            async with self._command_scope() as (repository, _):
                row = await repository.save_draft(*arguments)
        return self._draft(address, row)

    async def discard_draft(
        self, address: ComponentAddress, expected_draft_version: int
    ) -> None:
        self._registry.resolve(address)
        if self._command_scope is None:
            await self._repository.discard_draft(address, expected_draft_version)
        else:
            async with self._command_scope() as (repository, _):
                await repository.discard_draft(address, expected_draft_version)

    async def publish_draft(
        self,
        address: ComponentAddress,
        expected_draft_version: int,
        principal: str,
        *,
        idempotency_key: str | None = None,
    ) -> ComponentRevision[Any]:
        if idempotency_key is None:
            definition = self._registry.resolve(address)
            if self._command_scope is None:
                row = await self._repository.publish_draft(
                    address, expected_draft_version, principal, definition
                )
            else:
                async with self._command_scope() as (repository, _):
                    row = await repository.publish_draft(
                        address, expected_draft_version, principal, definition
                    )
            return self._revision(address, row)
        if self._command_scope is None:
            raise RuntimeError("idempotent component commands are not configured")
        fingerprint = request_fingerprint(
            {
                "address": self._address_payload(address),
                "expected_draft_version": expected_draft_version,
            }
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, PUBLISH_OPERATION, idempotency_key)
            if replay is not None:
                if replay.request_fingerprint != fingerprint:
                    raise IdempotencyKeyReused(
                        "idempotency key reused with a different request"
                    )
                return self._replayed_revision(address, replay.logical_result)
            definition = self._registry.resolve(address)
            revision = self._revision(
                address,
                await repository.publish_draft(
                    address, expected_draft_version, principal, definition
                ),
            )
            await replays.add(
                principal,
                PUBLISH_OPERATION,
                idempotency_key,
                fingerprint,
                self._revision_result(revision),
            )
        return revision

    async def rollback(
        self,
        address: ComponentAddress,
        revision_number: int,
        principal: str,
        *,
        idempotency_key: str | None = None,
    ) -> ComponentRevision[Any]:
        if idempotency_key is None:
            definition = self._registry.resolve(address)
            if self._command_scope is None:
                row = await self._repository.rollback(
                    address, revision_number, principal, definition
                )
            else:
                async with self._command_scope() as (repository, _):
                    row = await repository.rollback(
                        address, revision_number, principal, definition
                    )
            return self._revision(address, row)
        if self._command_scope is None:
            raise RuntimeError("idempotent component commands are not configured")
        fingerprint = request_fingerprint(
            {
                "address": self._address_payload(address),
                "revision_number": revision_number,
            }
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, ROLLBACK_OPERATION, idempotency_key)
            if replay is not None:
                if replay.request_fingerprint != fingerprint:
                    raise IdempotencyKeyReused(
                        "idempotency key reused with a different request"
                    )
                return self._replayed_revision(address, replay.logical_result)
            definition = self._registry.resolve(address)
            revision = self._revision(
                address,
                await repository.rollback(
                    address, revision_number, principal, definition
                ),
            )
            await replays.add(
                principal,
                ROLLBACK_OPERATION,
                idempotency_key,
                fingerprint,
                self._revision_result(revision),
            )
        return revision

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
        if schema_version != definition.schema_version:
            raise UnsupportedSchemaVersion(
                f"expected {definition.schema_version}, got {schema_version}"
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

    @staticmethod
    def _address_payload(address: ComponentAddress) -> dict[str, str | None]:
        return {
            "kind": str(address.kind),
            "scope_type": address.scope.type.value,
            "scope_key": address.scope.key,
        }

    def _revision_result(self, revision: ComponentRevision[Any]) -> dict[str, Any]:
        definition = self._registry.resolve(revision.address)
        return {
            "revision_id": str(revision.revision_id),
            "revision_number": revision.revision_number,
            "value": definition.serialize(revision.value),
            "schema_version": revision.schema_version,
            "based_on_revision_id": (
                str(revision.based_on_revision_id)
                if revision.based_on_revision_id is not None
                else None
            ),
            "restored_from_revision_id": (
                str(revision.restored_from_revision_id)
                if revision.restored_from_revision_id is not None
                else None
            ),
            "created_at": revision.created_at.isoformat(),
            "created_by": revision.created_by,
        }

    def _replayed_revision(
        self, address: ComponentAddress, result: dict[str, Any]
    ) -> ComponentRevision[Any]:
        definition = self._registry.resolve(address)
        return ComponentRevision(
            UUID(result["revision_id"]),
            address,
            result["revision_number"],
            definition.deserialize(result["value"]),
            result["schema_version"],
            UUID(result["based_on_revision_id"])
            if result["based_on_revision_id"] is not None
            else None,
            UUID(result["restored_from_revision_id"])
            if result["restored_from_revision_id"] is not None
            else None,
            datetime.fromisoformat(result["created_at"]),
            result["created_by"],
        )
