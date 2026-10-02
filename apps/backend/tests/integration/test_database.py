import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
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
        assert revision == "0003_call_ai_usage"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_call_ai_usage_round_trip(migrated_database_url: str) -> None:
    database = Database(migrated_database_url)
    tenant_id, call_id = uuid4(), uuid4()
    observed_at = datetime.now(UTC)
    try:
        async with database.transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, slug, display_name, business_type, status) "
                    "VALUES (:id, 'usage-test', 'Usage test', 'hotel', 'active')"
                ),
                {"id": tenant_id},
            )
            await session.execute(
                text(
                    "INSERT INTO call_sessions (id, tenant_id, execution_id, backend_execution_context, "
                    "channel, direction, provider, provider_call_id, room_name, status) "
                    "VALUES (:id, :tenant_id, :execution_id, '{}'::jsonb, 'sip', 'inbound', "
                    "'livekit', 'usage-test-call', 'usage-test-room', 'created')"
                ),
                {"id": call_id, "tenant_id": tenant_id, "execution_id": uuid4()},
            )
        async with database.transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO call_ai_usage (call_id, tenant_id, provider, service, model, "
                    "source, counters, first_observed_at, last_observed_at, estimated_cost_usd, "
                    "estimated_cost_source) VALUES (:call_id, :tenant_id, 'openai', 'llm', "
                    "'model-a', 'livekit_session_1_8_2', CAST(:counters AS jsonb), "
                    ":observed_at, :observed_at, :cost, 'test-rate-v1')"
                ),
                {
                    "call_id": call_id,
                    "tenant_id": tenant_id,
                    "observed_at": observed_at,
                    "cost": Decimal("1.14"),
                    "counters": json.dumps(
                        {
                            "input_tokens": 100,
                            "input_cached_tokens": 20,
                            "output_tokens": 10,
                        }
                    ),
                },
            )
        async with database.transaction() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT tenant_id, counters, estimated_cost_usd, estimated_cost_source, "
                        "provider_cost_usd FROM call_ai_usage WHERE call_id = :call_id"
                    ),
                    {"call_id": call_id},
                )
            ).one()
        assert row.tenant_id == tenant_id
        assert row.counters["input_cached_tokens"] == 20
        assert row.estimated_cost_usd == Decimal("1.14")
        assert row.estimated_cost_source == "test-rate-v1"
        assert row.provider_cost_usd is None
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_call_ai_usage_upgrade_downgrade_and_reupgrade(
    isolated_database_url: str,
    migrate_database: Callable[[str, str], Awaitable[None]],
    downgrade_database: Callable[[str, str], Awaitable[None]],
) -> None:
    await migrate_database(isolated_database_url, "0002_handoff_lifecycle")
    engine = create_async_engine(isolated_database_url)
    tenant_id, call_id = uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            assert await connection.scalar(
                text("SELECT to_regclass('public.call_ai_usage')")
            ) is None
            await connection.execute(
                text(
                    "INSERT INTO tenants (id, slug, display_name, business_type, status) "
                    "VALUES (:id, 'before-usage', 'Existing tenant', 'hotel', 'active')"
                ),
                {"id": tenant_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO call_sessions (id, tenant_id, execution_id, "
                    "backend_execution_context, channel, direction, provider, "
                    "provider_call_id, room_name, status) VALUES "
                    "(:id, :tenant_id, :execution_id, '{}'::jsonb, 'sip', "
                    "'inbound', 'livekit', 'before-usage-call', 'before-usage-room', 'created')"
                ),
                {"id": call_id, "tenant_id": tenant_id, "execution_id": uuid4()},
            )

        async def assert_existing_call(revision: str) -> None:
            async with engine.connect() as connection:
                assert await connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                ) == revision
                assert (
                    await connection.execute(
                        text(
                            "SELECT tenant_id, provider_call_id, room_name, status::text "
                            "FROM call_sessions WHERE id = :id"
                        ),
                        {"id": call_id},
                    )
                ).one() == (
                    tenant_id,
                    "before-usage-call",
                    "before-usage-room",
                    "created",
                )

        await migrate_database(isolated_database_url, "head")
        await assert_existing_call("0003_call_ai_usage")
        async with engine.begin() as connection:
            constraints = (
                await connection.execute(
                    text(
                        "SELECT conname, contype::text, confdeltype::text "
                        "FROM pg_constraint WHERE conrelid = 'call_ai_usage'::regclass "
                        "AND contype IN ('p', 'f')"
                    )
                )
            ).all()
            assert set(constraints) == {
                ("call_ai_usage_pkey", "p", " "),
                ("call_ai_usage_tenant_id_fkey", "f", "a"),
                ("fk_call_ai_usage_tenant_call", "f", "a"),
            }
            indexes = (
                await connection.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'call_ai_usage'")
                )
            ).scalars().all()
            assert set(indexes) == {
                "call_ai_usage_pkey",
                "ix_call_ai_usage_tenant_observed",
            }
            await connection.execute(
                text(
                    "INSERT INTO call_ai_usage "
                    "(call_id, tenant_id, provider, service, model, source, "
                    "counters, first_observed_at, last_observed_at) VALUES "
                    "(:call_id, :tenant_id, 'openai', 'llm', 'model-a', 'session', "
                    "'{}'::jsonb, now(), now())"
                ),
                {"call_id": call_id, "tenant_id": tenant_id},
            )

        await downgrade_database(isolated_database_url, "0002_handoff_lifecycle")
        await assert_existing_call("0002_handoff_lifecycle")
        async with engine.connect() as connection:
            assert await connection.scalar(
                text("SELECT to_regclass('public.call_ai_usage')")
            ) is None

        await migrate_database(isolated_database_url, "head")
        await assert_existing_call("0003_call_ai_usage")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO call_ai_usage "
                    "(call_id, tenant_id, provider, service, model, source, "
                    "counters, first_observed_at, last_observed_at) VALUES "
                    "(:call_id, :tenant_id, 'openai', 'llm', 'model-a', 'session', "
                    "'{}'::jsonb, now(), now())"
                ),
                {"call_id": call_id, "tenant_id": tenant_id},
            )
    finally:
        await engine.dispose()


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
        assert revision == "0003_call_ai_usage"
        assert set(nullable) == {
            ("handoff_attempt_id", "YES"),
            ("handoff_state", "YES"),
        }
        assert constraint == 1
    finally:
        await engine.dispose()
