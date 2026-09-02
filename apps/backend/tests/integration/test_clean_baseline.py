import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from backend_core.platform.database import Base, Database
from backend_core.platform.database.bootstrap import (
    baseline_needs_stamp,
    stamp_baseline,
)
from backend_core.platform.database.model_registry import load_models
from sqlalchemy import UniqueConstraint, text


async def _clear_schema(database: Database) -> None:
    async with database.transaction() as session:
        await session.execute(text("DROP SCHEMA public CASCADE"))
        await session.execute(text("CREATE SCHEMA public"))


async def _create_pre_alembic_schema(database: Database) -> None:
    async with database.transaction() as session:
        connection = await session.connection()
        await connection.run_sync(Base.metadata.create_all)
        for table in (
            "call_sessions",
            "capability_invocations",
            "capability_confirmations",
        ):
            await session.execute(
                text(f"ALTER TABLE {table} DROP COLUMN execution_snapshot_id")
            )


@pytest.mark.asyncio
async def test_clean_baseline_reconstructs_the_backend_schema(
    isolated_database_url: str,
) -> None:
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", isolated_database_url.replace("%", "%%"))
    database = Database(isolated_database_url)
    await _clear_schema(database)
    async with database.transaction() as session:
        await session.execute(
            text("CREATE TABLE control_plane_alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        await session.execute(text("INSERT INTO control_plane_alembic_version VALUES ('cp-1')"))
    await asyncio.to_thread(command.upgrade, config, "head")
    try:
        async with database.transaction() as session:
            version = await session.scalar(text("SELECT version_num FROM alembic_version"))
            tables = set(
                (await session.execute(
                    text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'")
                )).scalars()
            )
        assert version == "0002_execution_authority_cutover"
        load_models()
        assert tables == {"alembic_version", "control_plane_alembic_version", *Base.metadata.tables}

        await asyncio.to_thread(command.downgrade, config, "base")
        await asyncio.to_thread(command.upgrade, config, "head")
        async with database.transaction() as session:
            control_plane_version = await session.scalar(
                text("SELECT version_num FROM control_plane_alembic_version")
            )
        assert control_plane_version == "cp-1"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_matching_pre_alembic_schema_is_stamped_without_recreation(
    isolated_database_url: str,
) -> None:
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", isolated_database_url.replace("%", "%%"))
    database = Database(isolated_database_url)
    try:
        await _clear_schema(database)
        old_table = Base.metadata.tables["platform_release_profile_prompts"]
        old_constraint = UniqueConstraint(
            "release_id", "profile", name="uq_platform_release_profile"
        )
        current_constraint = next(
            constraint
            for constraint in old_table.constraints
            if constraint.name == "uq_platform_release_profile"
        )
        old_table.constraints.remove(current_constraint)
        old_table.append_constraint(old_constraint)
        try:
            async with database.transaction() as session:
                connection = await session.connection()
                await connection.run_sync(Base.metadata.create_all)
                for table in (
                    "call_sessions",
                    "capability_invocations",
                    "capability_confirmations",
                ):
                    await session.execute(
                        text(f"ALTER TABLE {table} DROP COLUMN execution_snapshot_id")
                    )
        finally:
            old_table.constraints.remove(old_constraint)
            old_table.append_constraint(current_constraint)
        async with database.transaction() as session:
            physically_present = await session.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'uq_platform_release_profile'
                    )
                    """
                )
            )
        assert physically_present is True
        async with database.transaction() as session:
            await session.execute(
                text("INSERT INTO platform_runtime_component_drafts (id, payload) VALUES (1, '{}')")
            )

        assert await baseline_needs_stamp(isolated_database_url)
        await asyncio.to_thread(stamp_baseline, isolated_database_url)

        async with database.transaction() as session:
            version = await session.scalar(text("SELECT version_num FROM alembic_version"))
            payload = await session.scalar(
                text("SELECT payload FROM platform_runtime_component_drafts WHERE id = 1")
            )
        assert version == "0001_initial_backend"
        assert payload == {}
        await asyncio.to_thread(command.upgrade, config, "head")
        async with database.transaction() as session:
            version = await session.scalar(text("SELECT version_num FROM alembic_version"))
        assert version == "0002_execution_authority_cutover"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_pre_alembic_schema_with_phase3_column_is_not_stamped(
    isolated_database_url: str,
) -> None:
    database = Database(isolated_database_url)
    try:
        await _clear_schema(database)
        await _create_pre_alembic_schema(database)
        async with database.transaction() as session:
            await session.execute(
                text("ALTER TABLE call_sessions ADD COLUMN execution_snapshot_id UUID")
            )
        with pytest.raises(RuntimeError, match="refusing to stamp"):
            await baseline_needs_stamp(isolated_database_url)
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_drifted_pre_alembic_schema_is_not_stamped(
    isolated_database_url: str,
) -> None:
    database = Database(isolated_database_url)
    try:
        await _clear_schema(database)
        await _create_pre_alembic_schema(database)
        async with database.transaction() as session:
            await session.execute(text("ALTER TABLE tenants DROP COLUMN display_name"))

        with pytest.raises(RuntimeError, match="refusing to stamp"):
            await baseline_needs_stamp(isolated_database_url)
        async with database.transaction() as session:
            version = await session.scalar(text("SELECT to_regclass('public.alembic_version')"))
        assert version is None
    finally:
        await database.close()
