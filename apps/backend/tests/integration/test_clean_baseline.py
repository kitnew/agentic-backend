import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from backend_core.platform.database import Database
from sqlalchemy import text


@pytest.mark.asyncio
async def test_clean_baseline_creates_only_component_release_schema(
    isolated_database_url: str,
) -> None:
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", isolated_database_url.replace("%", "%%"))
    await asyncio.to_thread(command.upgrade, config, "head")
    database = Database(isolated_database_url)
    try:
        async with database.transaction() as session:
            version = await session.scalar(text("SELECT version_num FROM alembic_version"))
            legacy = await session.scalar(
                text("SELECT to_regclass('public.tenant_config_revisions')")
            )
            release = await session.scalar(
                text("SELECT to_regclass('public.tenant_releases')")
            )
        assert version == "0001_component_release_baseline"
        assert legacy is None
        assert release == "tenant_releases"
    finally:
        await database.close()
