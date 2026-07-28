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


@pytest_asyncio.fixture(scope="session")
async def migrated_database_url(
    isolated_database_url: str,
) -> AsyncIterator[str]:
    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option(
        "sqlalchemy.url",
        isolated_database_url.replace("%", "%%"),
    )
    await asyncio.to_thread(command.upgrade, alembic, "head")
    try:
        yield isolated_database_url
    finally:
        await asyncio.to_thread(command.downgrade, alembic, "base")
