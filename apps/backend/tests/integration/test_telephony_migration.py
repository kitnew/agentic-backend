import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).parents[2]


@asynccontextmanager
async def temporary_database():
    raw = os.getenv("TEST_DATABASE_ADMIN_URL")
    if not raw:
        pytest.skip("set TEST_DATABASE_ADMIN_URL to run PostgreSQL migration tests")
    admin_url = make_url(raw)
    database_name = f"telephony_migration_{uuid4().hex}"
    admin = await asyncpg.connect(
        admin_url.set(drivername="postgresql").render_as_string(hide_password=False)
    )
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    database_url = admin_url.set(
        drivername="postgresql+asyncpg", database=database_name
    ).render_as_string(hide_password=False)
    try:
        yield database_url
    finally:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin.close()


def alembic(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def seed_legacy(
    database_url: str,
    numbers: list[str],
    *,
    schema_version: int = 4,
    slug: str = "legacy-hotel",
    status: str = "active",
    with_draft: bool = False,
) -> UUID:
    tenant_id = uuid4()
    revision_id = uuid4()
    config = {
        "schema_version": schema_version,
        "business": {"name": "Legacy Hotel", "type": "hotel"},
        "contact": {},
        "localization": {
            "default_locale": "sk-SK",
            "timezone": "Europe/Bratislava",
        },
        "agent": {
            "display_name": "Amelia",
            "greeting": "Hello",
            "profile": "hotel_assistant",
        },
        "conversation": {"scope": "property_only"},
        "capabilities": {},
        "handoff": {
            "destinations": {
                "reception": {
                    "description": "Reception",
                    "phone_number": "+421900000001",
                }
            }
        },
    }
    connection = await asyncpg.connect(database_url.replace("+asyncpg", ""))
    try:
        await connection.execute(
            "INSERT INTO tenants (id, slug, display_name, business_type) "
            "VALUES ($1, $2, 'Legacy Hotel', 'hotel')",
            tenant_id,
            slug,
        )
        await connection.execute(
            "INSERT INTO tenant_config_revisions "
            "(id, tenant_id, revision_number, schema_version, status, config, "
            "published_at, version) VALUES ($1, $2, 1, $3, 'published', $4::jsonb, "
            "now(), 1)",
            revision_id,
            tenant_id,
            schema_version,
            json.dumps(config),
        )
        await connection.execute(
            "UPDATE tenants SET active_config_revision_id = $1 WHERE id = $2",
            revision_id,
            tenant_id,
        )
        if status != "active":
            await connection.execute(
                "UPDATE tenants SET status = $1 WHERE id = $2", status, tenant_id
            )
        if with_draft:
            await connection.execute(
                "INSERT INTO tenant_config_revisions "
                "(id, tenant_id, revision_number, schema_version, status, config, version) "
                "VALUES ($1, $2, 2, $3, 'draft', $4::jsonb, 1)",
                uuid4(),
                tenant_id,
                schema_version,
                json.dumps(config),
            )
        for number in numbers:
            await connection.execute(
                "INSERT INTO inbound_routes "
                "(id, tenant_id, normalized_did, enabled) VALUES ($1, $2, $3, true)",
                uuid4(),
                tenant_id,
                number,
            )
    finally:
        await connection.close()
    return tenant_id


@pytest.mark.asyncio
async def test_legacy_route_and_handoff_migrate_and_conflicts_abort() -> None:
    async with temporary_database() as database_url:
        config = alembic(database_url)
        await asyncio.to_thread(command.upgrade, config, "20260819_0028")
        tenant_id = await seed_legacy(database_url, ["+421551234567"])
        v1_tenant_id = await seed_legacy(
            database_url,
            ["+421551234569"],
            schema_version=1,
            slug="legacy-v1-hotel",
        )
        v2_tenant_id = await seed_legacy(
            database_url,
            ["+421551234570"],
            schema_version=2,
            slug="legacy-v2-hotel",
        )
        v3_tenant_id = await seed_legacy(
            database_url,
            ["+421551234571"],
            schema_version=3,
            slug="legacy-v3-hotel",
        )
        draft_tenant_id = await seed_legacy(
            database_url,
            ["+421551234572"],
            slug="legacy-draft-hotel",
            with_draft=True,
        )
        disabled_tenant_id = await seed_legacy(
            database_url,
            ["+421551234573"],
            slug="legacy-disabled-hotel",
            status="suspended",
        )
        empty_tenant_id = await seed_legacy(
            database_url,
            [],
            slug="legacy-empty-hotel",
        )
        await asyncio.to_thread(command.upgrade, config, "head")
        connection = await asyncpg.connect(database_url.replace("+asyncpg", ""))
        try:
            row = await connection.fetchrow(
                "SELECT phone_number, handoff_destinations FROM tenant_telephony "
                "WHERE tenant_id = $1",
                tenant_id,
            )
            revision = await connection.fetchrow(
                "SELECT schema_version, config FROM tenant_config_revisions "
                "WHERE tenant_id = $1 AND status = 'published'",
                tenant_id,
            )
            v1_projection = await connection.fetchrow(
                "SELECT phone_number, config_revision_id FROM tenant_telephony "
                "WHERE tenant_id = $1",
                v1_tenant_id,
            )
            v1_revision = await connection.fetchrow(
                "SELECT schema_version, status FROM tenant_config_revisions "
                "WHERE tenant_id = $1 AND status = 'published'",
                v1_tenant_id,
            )
            v2_projection = await connection.fetchrow(
                "SELECT phone_number FROM tenant_telephony WHERE tenant_id = $1",
                v2_tenant_id,
            )
            v3_projection = await connection.fetchrow(
                "SELECT phone_number FROM tenant_telephony WHERE tenant_id = $1",
                v3_tenant_id,
            )
            draft_revisions = await connection.fetch(
                "SELECT schema_version, status FROM tenant_config_revisions "
                "WHERE tenant_id = $1 ORDER BY revision_number",
                draft_tenant_id,
            )
            disabled_projection = await connection.fetchrow(
                "SELECT phone_number FROM tenant_telephony WHERE tenant_id = $1",
                disabled_tenant_id,
            )
            empty_projection = await connection.fetchrow(
                "SELECT phone_number FROM tenant_telephony WHERE tenant_id = $1",
                empty_tenant_id,
            )
        finally:
            await connection.close()
        destinations = json.loads(row["handoff_destinations"])
        migrated_config = json.loads(revision["config"])
        assert row["phone_number"] == "+421551234567"
        assert destinations["reception"]["phone_number"] == (
            "+421900000001"
        )
        assert revision["schema_version"] == 5
        assert migrated_config["telephony"]["phone_number"] == "+421551234567"
        # V1 has no lossless V5 representation. The migration retires its
        # legacy route without creating a projection that is not backed by a
        # canonical published Telephony config (fail closed).
        assert v1_projection is None
        assert v1_revision["schema_version"] == 1
        assert v2_projection is None
        assert v3_projection is None
        assert [(row["schema_version"], row["status"]) for row in draft_revisions] == [
            (5, "published"),
            (5, "draft"),
        ]
        assert disabled_projection["phone_number"] == "+421551234573"
        assert empty_projection["phone_number"] is None

    async with temporary_database() as database_url:
        config = alembic(database_url)
        await asyncio.to_thread(command.upgrade, config, "20260819_0028")
        await seed_legacy(database_url, ["+421551234567", "+421551234568"])
        with pytest.raises(Exception, match="multiple enabled DIDs"):
            await asyncio.to_thread(command.upgrade, config, "head")
