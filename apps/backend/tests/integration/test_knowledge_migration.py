import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from backend_core.platform.database import Database
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).parents[2]


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


@pytest.mark.asyncio
async def test_legacy_kb_backfill_preserves_prompt_set_call_and_safe_downgrade(
    isolated_database_url: str,
) -> None:
    config = alembic_config(isolated_database_url)
    await asyncio.to_thread(command.downgrade, config, "20260810_0018")
    ids = {
        name: uuid4()
        for name in (
            "tenant",
            "config",
            "system",
            "system_revision",
            "profile",
            "profile_revision",
            "tenant_prompt",
            "tenant_prompt_revision",
            "base",
            "base_revision",
            "prompt_set",
            "prompt_set_revision",
            "call",
        )
    }
    legacy_text = "Legacy knowledge\nwith exact content.\n"
    database = Database(isolated_database_url)
    try:
        async with database.transaction() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants "
                    "(id, slug, display_name, business_type, status) "
                    "VALUES (:id, 'migration-kb-hotel', 'Migration KB', 'hotel', 'active')"
                ),
                {"id": ids["tenant"]},
            )
            await session.execute(
                text(
                    "INSERT INTO tenant_config_revisions "
                    "(id, tenant_id, revision_number, schema_version, status, config, version) "
                    "VALUES (:id, :tenant, 1, 3, 'published', CAST(:config AS jsonb), 1)"
                ),
                {
                    "id": ids["config"],
                    "tenant": ids["tenant"],
                    "config": json.dumps({"schema_version": 3}),
                },
            )
            for table, parent_id, key in (
                ("system_prompts", ids["system"], "migration_system"),
                ("profile_prompts", ids["profile"], "migration_profile"),
            ):
                await session.execute(
                    text(f"INSERT INTO {table} (id, key) VALUES (:id, :key)"),
                    {"id": parent_id, "key": key},
                )
            await session.execute(
                text(
                    "INSERT INTO tenant_prompts (id, tenant_id) VALUES (:id, :tenant)"
                ),
                {
                    "id": ids["tenant_prompt"],
                    "base": ids["base"],
                    "set": ids["prompt_set"],
                    "tenant": ids["tenant"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO knowledge_bases (id, tenant_id) "
                    "VALUES (:base, :tenant)"
                ),
                {"base": ids["base"], "tenant": ids["tenant"]},
            )
            await session.execute(
                text("INSERT INTO prompt_sets (id, tenant_id) VALUES (:set, :tenant)"),
                {"set": ids["prompt_set"], "tenant": ids["tenant"]},
            )
            for table, row_id, parent_name, parent_id, content in (
                (
                    "system_prompt_revisions",
                    ids["system_revision"],
                    "system_prompt_id",
                    ids["system"],
                    "system",
                ),
                (
                    "profile_prompt_revisions",
                    ids["profile_revision"],
                    "profile_prompt_id",
                    ids["profile"],
                    "profile",
                ),
            ):
                await session.execute(
                    text(
                        f"INSERT INTO {table} "
                        f"(id, {parent_name}, revision_number, status, text, version) "
                        "VALUES (:id, :parent, 1, 'published', :content, 1)"
                    ),
                    {"id": row_id, "parent": parent_id, "content": content},
                )
            await session.execute(
                text(
                    "INSERT INTO tenant_prompt_revisions "
                    "(id, tenant_prompt_id, tenant_id, revision_number, status, text, version) "
                    "VALUES (:id, :parent, :tenant, 1, 'published', 'tenant', 1)"
                ),
                {
                    "id": ids["tenant_prompt_revision"],
                    "parent": ids["tenant_prompt"],
                    "tenant": ids["tenant"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO knowledge_base_revisions "
                    "(id, knowledge_base_id, tenant_id, revision_number, status, text, version) "
                    "VALUES (:kb_revision, :base, :tenant, 1, 'published', :content, 1)"
                ),
                {
                    "tenant": ids["tenant"],
                    "kb_revision": ids["base_revision"],
                    "base": ids["base"],
                    "content": legacy_text,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO prompt_set_revisions "
                    "(id, prompt_set_id, tenant_id, revision_number, status, "
                    "system_prompt_revision_id, profile_prompt_revision_id, "
                    "tenant_prompt_revision_id, knowledge_base_revision_id, version) "
                    "VALUES (:id, :set, :tenant, 1, 'published', :system, :profile, "
                    ":tenant_prompt, :knowledge, 1)"
                ),
                {
                    "id": ids["prompt_set_revision"],
                    "set": ids["prompt_set"],
                    "tenant": ids["tenant"],
                    "system": ids["system_revision"],
                    "profile": ids["profile_revision"],
                    "tenant_prompt": ids["tenant_prompt_revision"],
                    "knowledge": ids["base_revision"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO call_sessions "
                    "(id, tenant_id, tenant_config_revision_id, prompt_set_revision_id, "
                    "channel, direction, provider, provider_call_id, room_name, status) "
                    "VALUES (:id, :tenant, :config, :set, 'web', 'inbound', "
                    "'migration', 'migration-call', 'migration-room', 'created')"
                ),
                {
                    "id": ids["call"],
                    "tenant": ids["tenant"],
                    "config": ids["config"],
                    "set": ids["prompt_set_revision"],
                },
            )
    finally:
        await database.close()

    await asyncio.to_thread(command.upgrade, config, "20260810_0019")
    database = Database(isolated_database_url)
    try:
        async with database.transaction() as session:
            migrated = (
                await session.execute(
                    text(
                        "SELECT kbr.id, psr.knowledge_base_revision_id, "
                        "link.position, document.key, revision.revision_number, "
                        "revision.content "
                        "FROM call_sessions call "
                        "JOIN prompt_set_revisions psr ON psr.id = call.prompt_set_revision_id "
                        "JOIN knowledge_base_revisions kbr "
                        "ON kbr.id = psr.knowledge_base_revision_id "
                        "JOIN knowledge_base_revision_documents link "
                        "ON link.knowledge_base_revision_id = kbr.id "
                        "JOIN knowledge_documents document "
                        "ON document.id = link.knowledge_document_id "
                        "JOIN knowledge_document_revisions revision "
                        "ON revision.id = link.knowledge_document_revision_id "
                        "WHERE call.id = :call"
                    ),
                    {"call": ids["call"]},
                )
            ).one()
            assert migrated == (
                ids["base_revision"],
                ids["base_revision"],
                0,
                "knowledge",
                1,
                legacy_text,
            )
            assert not await session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'knowledge_base_revisions' "
                    "AND column_name = 'text')"
                )
            )
            extra_document, extra_revision = uuid4(), uuid4()
            await session.execute(
                text(
                    "INSERT INTO knowledge_documents "
                    "(id, knowledge_base_id, tenant_id, key) "
                    "VALUES (:document, :base, :tenant, 'rooms')"
                ),
                {
                    "document": extra_document,
                    "base": ids["base"],
                    "tenant": ids["tenant"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO knowledge_document_revisions "
                    "(id, knowledge_document_id, knowledge_base_id, tenant_id, "
                    "revision_number, media_type, content, content_hash) "
                    "VALUES (:revision, :document, :base, :tenant, 1, "
                    "'text/markdown', 'rooms', "
                    "'3f0c81f8f7aa2fb0dfc6a1f8bfaea95dc373fa2dc799fff4903f20d4e552203a')"
                ),
                {
                    "document": extra_document,
                    "revision": extra_revision,
                    "base": ids["base"],
                    "tenant": ids["tenant"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO knowledge_base_revision_documents "
                    "(knowledge_base_revision_id, knowledge_document_revision_id, "
                    "tenant_id, knowledge_base_id, knowledge_document_id, position) "
                    "VALUES (:kb_revision, :revision, :tenant, :base, :document, 1)"
                ),
                {
                    "document": extra_document,
                    "revision": extra_revision,
                    "base": ids["base"],
                    "tenant": ids["tenant"],
                    "kb_revision": ids["base_revision"],
                },
            )
    finally:
        await database.close()

    with pytest.raises(RuntimeError, match="not legacy-compatible"):
        await asyncio.to_thread(command.downgrade, config, "20260810_0018")

    database = Database(isolated_database_url)
    try:
        async with database.transaction() as session:
            await session.execute(
                text(
                    "DELETE FROM knowledge_base_revision_documents "
                    "WHERE knowledge_document_revision_id = :revision"
                ),
                {"revision": extra_revision},
            )
            await session.execute(
                text("DELETE FROM knowledge_documents WHERE id = :document"),
                {"document": extra_document},
            )
    finally:
        await database.close()

    await asyncio.to_thread(command.downgrade, config, "20260810_0018")
    database = Database(isolated_database_url)
    try:
        async with database.transaction() as session:
            assert (
                await session.scalar(
                    text("SELECT text FROM knowledge_base_revisions WHERE id = :id"),
                    {"id": ids["base_revision"]},
                )
                == legacy_text
            )
            for table, row_id in (
                ("call_sessions", ids["call"]),
                ("prompt_set_revisions", ids["prompt_set_revision"]),
                ("prompt_sets", ids["prompt_set"]),
                ("knowledge_base_revisions", ids["base_revision"]),
                ("knowledge_bases", ids["base"]),
                ("tenant_prompt_revisions", ids["tenant_prompt_revision"]),
                ("tenant_prompts", ids["tenant_prompt"]),
                ("tenant_config_revisions", ids["config"]),
                ("tenants", ids["tenant"]),
                ("system_prompt_revisions", ids["system_revision"]),
                ("system_prompts", ids["system"]),
                ("profile_prompt_revisions", ids["profile_revision"]),
                ("profile_prompts", ids["profile"]),
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE id = :id"),
                    {"id": row_id},
                )
    finally:
        await database.close()
        await asyncio.to_thread(command.upgrade, config, "head")
