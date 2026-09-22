from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from backend_core.platform.database import Database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_migrations_and_transaction_round_trip(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.transaction() as session:
            await session.execute(
                text(
                    "CREATE TABLE persistence_probe "
                    "(id integer PRIMARY KEY, value text NOT NULL)"
                )
            )
            await session.execute(
                text("INSERT INTO persistence_probe VALUES (1, :value)"),
                {"value": "committed"},
            )

        with pytest.raises(RuntimeError):
            async with database.transaction() as session:
                await session.execute(
                    text("INSERT INTO persistence_probe VALUES (2, 'rolled back')")
                )
                raise RuntimeError("force rollback")

        async with database.transaction() as session:
            values = (
                (
                    await session.execute(
                        text("SELECT value FROM persistence_probe ORDER BY id")
                    )
                )
                .scalars()
                .all()
            )
            revision = await session.scalar(
                text("SELECT version_num FROM alembic_version")
            )

        assert values == ["committed"]
        assert revision == "0002_handoff_lifecycle"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_handoff_migration_preserves_existing_call_rows(
    isolated_database_url: str,
    migrate_database: Callable[[str, str], Awaitable[None]],
) -> None:
    await migrate_database(isolated_database_url, "0001_initial_backend")
    engine = create_async_engine(isolated_database_url)
    tenant_id = uuid4()
    now = datetime.now(UTC)
    rows = [
        (uuid4(), "connected", now, now, None, None, None),
        (uuid4(), "ended", now, now, now, None, "handoff-existing"),
        (uuid4(), "failed", None, None, now, "provider_failed", None),
    ]
    try:
        async with engine.begin() as connection:
            # Immutable 0001 imports live ORM metadata. Remove fields that were not
            # present when production actually applied it to recreate that schema.
            await connection.execute(
                text(
                    "ALTER TABLE call_sessions "
                    "DROP CONSTRAINT ck_call_sessions_handoff_attempt_fields, "
                    "DROP COLUMN handoff_state, DROP COLUMN handoff_attempt_id"
                )
            )
            await connection.execute(text("DROP TYPE handoff_state"))
            await connection.execute(
                text(
                    "INSERT INTO tenants "
                    "(id, slug, display_name, business_type, status) "
                    "VALUES (:id, 'existing', 'Existing tenant', 'hotel', 'active')"
                ),
                {"id": tenant_id},
            )
            for index, (
                call_id,
                status,
                started_at,
                connected_at,
                ended_at,
                failure_reason,
                handoff_identity,
            ) in enumerate(rows):
                await connection.execute(
                    text(
                        "INSERT INTO call_sessions "
                        "(id, tenant_id, execution_id, backend_execution_context, "
                        "channel, direction, provider, provider_call_id, room_name, "
                        "status, started_at, connected_at, ended_at, failure_reason, "
                        "handoff_participant_identity) VALUES "
                        "(:id, :tenant_id, :execution_id, '{}'::jsonb, 'sip', "
                        "'inbound', 'livekit', :provider_call_id, :room_name, :status, "
                        ":started_at, :connected_at, :ended_at, :failure_reason, "
                        ":handoff_identity)"
                    ),
                    {
                        "id": call_id,
                        "tenant_id": tenant_id,
                        "execution_id": uuid4(),
                        "provider_call_id": f"existing-{index}",
                        "room_name": f"existing-room-{index}",
                        "status": status,
                        "started_at": started_at,
                        "connected_at": connected_at,
                        "ended_at": ended_at,
                        "failure_reason": failure_reason,
                        "handoff_identity": handoff_identity,
                    },
                )

        await migrate_database(isolated_database_url, "head")

        async with engine.connect() as connection:
            preserved = (
                await connection.execute(
                    text(
                        "SELECT id, provider_call_id, room_name, status::text, "
                        "started_at, connected_at, ended_at, failure_reason, "
                        "handoff_participant_identity, handoff_attempt_id, "
                        "handoff_state::text "
                        "FROM call_sessions ORDER BY provider_call_id"
                    )
                )
            ).all()
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            nullable = (
                await connection.execute(
                    text(
                        "SELECT column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'call_sessions' "
                        "AND column_name IN ('handoff_attempt_id', 'handoff_state')"
                    )
                )
            ).all()
            constraint = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conname = 'ck_call_sessions_handoff_attempt_fields'"
                )
            )

        expected = {
            (
                call_id,
                f"existing-{index}",
                f"existing-room-{index}",
                status,
                started_at,
                connected_at,
                ended_at,
                failure_reason,
                handoff_identity,
                None,
                None,
            )
            for index, (
                call_id,
                status,
                started_at,
                connected_at,
                ended_at,
                failure_reason,
                handoff_identity,
            ) in enumerate(rows)
        }
        assert set(preserved) == expected
        assert revision == "0002_handoff_lifecycle"
        assert set(nullable) == {
            ("handoff_attempt_id", "YES"),
            ("handoff_state", "YES"),
        }
        assert constraint == 1
    finally:
        await engine.dispose()
