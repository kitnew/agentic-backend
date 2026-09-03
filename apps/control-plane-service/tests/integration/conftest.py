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

SERVICE_ROOT = Path(__file__).parents[2]


def dsn(url: URL) -> str:
    return url.render_as_string(hide_password=False)


@pytest_asyncio.fixture
async def isolated_database_url() -> AsyncIterator[str]:
    raw = os.getenv("TEST_DATABASE_ADMIN_URL")
    if not raw:
        pytest.skip("set TEST_DATABASE_ADMIN_URL to run PostgreSQL integration tests")
    admin_url = make_url(raw)
    database_name = f"control_plane_test_{uuid4().hex}"
    connection = await asyncpg.connect(dsn(admin_url.set(drivername="postgresql")))
    try:
        await connection.execute(f'CREATE DATABASE "{database_name}"')
        yield dsn(
            admin_url.set(drivername="postgresql+asyncpg", database=database_name)
        )
    finally:
        await connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await connection.close()


@pytest.fixture
def alembic_config(isolated_database_url: str) -> Config:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", isolated_database_url.replace("%", "%%"))
    return config


@pytest_asyncio.fixture
async def migrated_database_url(
    isolated_database_url: str, alembic_config: Config
) -> str:
    await asyncio.to_thread(command.upgrade, alembic_config, "head")
    return isolated_database_url
