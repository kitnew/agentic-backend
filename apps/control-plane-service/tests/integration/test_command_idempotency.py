from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from control_plane.application.command_support import IdempotencyKeyReused
from control_plane.application.components import ComponentService
from control_plane.application.ports.repositories import ComponentRepository
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinition,
    ComponentDefinitionRegistry,
    ComponentKind,
    ScopeType,
    TenantScope,
)
from control_plane.domain.components.errors import ComponentNotFound
from control_plane.infrastructure.persistence.command_transactions import (
    component_command_scope,
)
from control_plane.infrastructure.persistence.database import Database
from control_plane.infrastructure.persistence.repository import (
    SqlAlchemyComponentRepository,
)
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


class ExampleSettings(BaseModel):
    enabled: bool
    label: str


def registry() -> ComponentDefinitionRegistry:
    result = ComponentDefinitionRegistry()
    result.register(
        ComponentDefinition(
            ComponentKind("example.settings"),
            ExampleSettings,
            frozenset({ScopeType.TENANT}),
            1,
        )
    )
    return result


def service(database: Database) -> ComponentService:
    return ComponentService(
        registry(),
        cast(ComponentRepository, SqlAlchemyComponentRepository(database.sessions)),
        component_command_scope(database.sessions),
    )


def address(key: str) -> ComponentAddress:
    return ComponentAddress(ComponentKind("example.settings"), TenantScope(key))


async def save(
    components: ComponentService,
    target: ComponentAddress,
    label: str,
    *,
    expected_version: int | None = None,
    expected_active=None,
):
    return await components.save_draft(
        target,
        {"enabled": True, "label": label},
        expected_version,
        expected_active,
        "draft-editor",
    )


async def counts(database: Database) -> tuple[int, int, int]:
    async with database.sessions() as session:
        draft_count = await session.scalar(
            text("SELECT count(*) FROM control_plane.configuration_component_drafts")
        )
        revision_count = await session.scalar(
            text("SELECT count(*) FROM control_plane.configuration_component_revisions")
        )
        replay_count = await session.scalar(
            text("SELECT count(*) FROM control_plane.idempotency_replays")
        )
    assert (
        draft_count is not None
        and revision_count is not None
        and replay_count is not None
    )
    return draft_count, revision_count, replay_count


@asynccontextmanager
async def database_for(url: str) -> AsyncIterator[Database]:
    database = Database(url)
    try:
        yield database
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_same_request_replays_same_logical_result_once(
    migrated_database_url: str,
) -> None:
    async with database_for(migrated_database_url) as database:
        components = service(database)
        target = address("same-request")
        draft = await save(components, target, "one")

        first = await components.publish_draft(
            target, draft.version, principal="management:alice", idempotency_key="key-1"
        )
        replay = await components.publish_draft(
            target, draft.version, principal="management:alice", idempotency_key="key-1"
        )

        assert replay == first
        assert await counts(database) == (0, 1, 1)


@pytest.mark.asyncio
async def test_idempotency_key_reused_with_different_request_conflicts(
    migrated_database_url: str,
) -> None:
    async with database_for(migrated_database_url) as database:
        components = service(database)
        first_target = address("conflict-first")
        second_target = address("conflict-second")
        first = await save(components, first_target, "one")
        second = await save(components, second_target, "two")
        await components.publish_draft(
            first_target,
            first.version,
            principal="management:alice",
            idempotency_key="same-key",
        )

        with pytest.raises(IdempotencyKeyReused):
            await components.publish_draft(
                second_target,
                second.version,
                principal="management:alice",
                idempotency_key="same-key",
            )

        assert await counts(database) == (1, 1, 1)


@pytest.mark.asyncio
async def test_idempotency_key_is_scoped_by_principal(
    migrated_database_url: str,
) -> None:
    async with database_for(migrated_database_url) as database:
        components = service(database)
        first_target = address("principal-first")
        second_target = address("principal-second")
        first = await save(components, first_target, "one")
        second = await save(components, second_target, "two")

        await components.publish_draft(
            first_target,
            first.version,
            principal="management:alice",
            idempotency_key="shared-key",
        )
        await components.publish_draft(
            second_target,
            second.version,
            principal="management:bob",
            idempotency_key="shared-key",
        )

        assert await counts(database) == (0, 2, 2)


@pytest.mark.asyncio
async def test_idempotency_key_is_scoped_by_logical_operation(
    migrated_database_url: str,
) -> None:
    async with database_for(migrated_database_url) as database:
        components = service(database)
        target = address("operation-scope")
        draft = await save(components, target, "one")
        published = await components.publish_draft(
            target,
            draft.version,
            principal="management:alice",
            idempotency_key="shared-key",
        )

        restored = await components.rollback(
            target,
            published.revision_number,
            principal="management:alice",
            idempotency_key="shared-key",
        )

        assert restored.revision_id != published.revision_id
        assert restored.restored_from_revision_id == published.revision_id
        assert await counts(database) == (0, 2, 2)


@pytest.mark.asyncio
async def test_replay_precedes_stale_concurrency_validation(
    migrated_database_url: str,
) -> None:
    async with database_for(migrated_database_url) as database:
        components = service(database)
        target = address("replay-before-concurrency")
        draft = await save(components, target, "one")
        published = await components.publish_draft(
            target,
            draft.version,
            principal="management:alice",
            idempotency_key="key-1",
        )
        next_draft = await save(
            components,
            target,
            "two",
            expected_active=published.revision_id,
        )
        await save(
            components,
            target,
            "three",
            expected_version=next_draft.version,
            expected_active=published.revision_id,
        )

        replay = await components.publish_draft(
            target,
            draft.version,
            principal="management:alice",
            idempotency_key="key-1",
        )

        assert replay == published
        assert (await components.get_draft(target)).version == 2
        assert await counts(database) == (1, 1, 1)


@pytest.mark.asyncio
async def test_lost_response_retry_returns_original_committed_result(
    migrated_database_url: str,
) -> None:
    async with database_for(migrated_database_url) as database:
        components = service(database)
        target = address("lost-response")
        draft = await save(components, target, "one")

        async def commit_then_lose_response() -> None:
            await components.publish_draft(
                target,
                draft.version,
                principal="management:alice",
                idempotency_key="lost-key",
            )
            raise ConnectionError("response lost")

        with pytest.raises(ConnectionError, match="response lost"):
            await commit_then_lose_response()
        replay = await components.publish_draft(
            target,
            draft.version,
            principal="management:alice",
            idempotency_key="lost-key",
        )

        assert replay.revision_number == 1
        assert await counts(database) == (0, 1, 1)


@pytest.mark.asyncio
async def test_mutation_failure_persists_neither_partial_state_nor_replay(
    migrated_database_url: str,
) -> None:
    async with database_for(migrated_database_url) as database:
        components = service(database)
        target = address("mutation-failure")
        draft = await save(components, target, "one")
        async with database.sessions.begin() as session:
            await session.execute(
                text(
                    "CREATE FUNCTION control_plane.fail_revision_insert() RETURNS trigger "
                    "LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''revision insert failed''; END'"
                )
            )
            await session.execute(
                text(
                    "CREATE TRIGGER fail_revision_insert BEFORE INSERT ON "
                    "control_plane.configuration_component_revisions FOR EACH ROW "
                    "EXECUTE FUNCTION control_plane.fail_revision_insert()"
                )
            )

        with pytest.raises(DBAPIError, match="revision insert failed"):
            await components.publish_draft(
                target,
                draft.version,
                principal="management:alice",
                idempotency_key="key-1",
            )

        assert await counts(database) == (1, 0, 0)


@pytest.mark.asyncio
async def test_replay_persistence_failure_rolls_back_mutation(
    migrated_database_url: str,
) -> None:
    async with database_for(migrated_database_url) as database:
        components = service(database)
        target = address("replay-failure")
        draft = await save(components, target, "one")
        async with database.sessions.begin() as session:
            await session.execute(
                text(
                    "CREATE FUNCTION control_plane.fail_replay_insert() RETURNS trigger "
                    "LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''replay insert failed''; END'"
                )
            )
            await session.execute(
                text(
                    "CREATE TRIGGER fail_replay_insert BEFORE INSERT ON "
                    "control_plane.idempotency_replays FOR EACH ROW "
                    "EXECUTE FUNCTION control_plane.fail_replay_insert()"
                )
            )

        with pytest.raises(DBAPIError, match="replay insert failed"):
            await components.publish_draft(
                target,
                draft.version,
                principal="management:alice",
                idempotency_key="key-1",
            )

        assert await counts(database) == (1, 0, 0)


@pytest.mark.asyncio
async def test_application_owned_transaction_commits_mutation_and_replay_together(
    migrated_database_url: str,
) -> None:
    async with database_for(migrated_database_url) as database:
        components = service(database)
        target = address("successful-transaction")
        draft = await save(components, target, "one")

        published = await components.publish_draft(
            target,
            draft.version,
            principal="management:alice",
            idempotency_key="key-1",
        )

        assert published.created_by == "management:alice"
        assert await counts(database) == (0, 1, 1)
        async with database.sessions() as session:
            replay_principal = await session.scalar(
                text("SELECT principal FROM control_plane.idempotency_replays")
            )
        assert replay_principal == "management:alice"


@pytest.mark.asyncio
async def test_mutation_without_draft_creates_no_replay(
    migrated_database_url: str,
) -> None:
    async with database_for(migrated_database_url) as database:
        components = service(database)

        with pytest.raises(ComponentNotFound):
            await components.publish_draft(
                address("missing-draft"),
                1,
                principal="management:alice",
                idempotency_key="key-1",
            )

        assert await counts(database) == (0, 0, 0)
