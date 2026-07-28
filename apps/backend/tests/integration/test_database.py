import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from backend_core.platform.database import Database
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url

BACKEND_ROOT = Path(__file__).parents[2]


def dsn(url: URL) -> str:
    return url.render_as_string(hide_password=False)


@pytest_asyncio.fixture(scope="session")
async def isolated_database_url() -> AsyncIterator[str]:
    raw_admin_url = os.getenv("TEST_DATABASE_ADMIN_URL")
    if not raw_admin_url:
        pytest.skip("set TEST_DATABASE_ADMIN_URL to run PostgreSQL integration tests")

    admin_url = make_url(raw_admin_url)
    database_name = f"backend_test_{uuid4().hex}"
    admin_connection = await asyncpg.connect(
        dsn(admin_url.set(drivername="postgresql"))
    )

    try:
        await admin_connection.execute(f'CREATE DATABASE "{database_name}"')
        yield dsn(
            admin_url.set(
                drivername="postgresql+asyncpg",
                database=database_name,
            )
        )
    finally:
        await admin_connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin_connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin_connection.close()


@pytest.mark.asyncio
async def test_migrations_and_transaction_round_trip(
    isolated_database_url: str,
) -> None:
    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option(
        "sqlalchemy.url",
        isolated_database_url.replace("%", "%%"),
    )
    await asyncio.to_thread(command.upgrade, alembic, "head")

    database = Database(isolated_database_url)
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
        assert revision == "20260728_0001"
    finally:
        await database.close()
