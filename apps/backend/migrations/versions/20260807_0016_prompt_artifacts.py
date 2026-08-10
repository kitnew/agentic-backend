"""Split prompt bundles into independently versioned artifacts and PromptSets.

The migration map is retained for the downgrade: it restores each call's old
bundle and each tenant's old active config before removing the new rows.
Running Alembic upgrade at the current head is a no-op; this migration is not
designed for partial/manual reruns.

Revision ID: 20260807_0016
Revises: 20260806_0015
"""

import json
from copy import deepcopy
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260807_0016"
down_revision = "20260806_0015"
branch_labels = None
depends_on = None

prompt_status = postgresql.ENUM("draft", "published", "archived", name="prompt_revision_status")


def _revision_table(name: str, parent: str, tenant: bool = False) -> None:
    columns = [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(parent, sa.Uuid(), nullable=False),
    ]
    if tenant:
        columns.extend([sa.Column("tenant_id", sa.Uuid(), nullable=False), sa.UniqueConstraint("tenant_id", "id")])
    columns.extend([
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", prompt_status, nullable=False, server_default="draft"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(parent, "revision_number"),
    ])
    op.create_table(name, *columns)
    op.create_index(f"uq_{name}_one_draft", name, [parent], unique=True, postgresql_where=sa.text("status = 'draft'"))


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("prompt_artifact_migration_map"):
        return
    op.create_table("system_prompts", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("key", sa.String(100), nullable=False, unique=True))
    op.create_table("profile_prompts", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("key", sa.String(100), nullable=False, unique=True))
    op.create_table("tenant_prompts", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), nullable=False, unique=True))
    op.create_table("knowledge_bases", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), nullable=False, unique=True))
    _revision_table("system_prompt_revisions", "system_prompt_id")
    _revision_table("profile_prompt_revisions", "profile_prompt_id")
    _revision_table("tenant_prompt_revisions", "tenant_prompt_id", tenant=True)
    _revision_table("knowledge_base_revisions", "knowledge_base_id", tenant=True)
    op.create_table("prompt_sets", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("tenant_id", sa.Uuid(), nullable=False, unique=True))
    op.create_table(
        "prompt_set_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("prompt_set_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", prompt_status, nullable=False, server_default="draft"),
        sa.Column("system_prompt_revision_id", sa.Uuid(), nullable=False),
        sa.Column("profile_prompt_revision_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_prompt_revision_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_revision_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("prompt_set_id", "revision_number"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_index("uq_prompt_set_revisions_one_draft", "prompt_set_revisions", ["prompt_set_id"], unique=True, postgresql_where=sa.text("status = 'draft'"))
    for name, column, target in (
        ("system_prompt_revisions", "system_prompt_id", "system_prompts"),
        ("profile_prompt_revisions", "profile_prompt_id", "profile_prompts"),
        ("tenant_prompt_revisions", "tenant_prompt_id", "tenant_prompts"),
        ("knowledge_base_revisions", "knowledge_base_id", "knowledge_bases"),
        ("prompt_sets", "tenant_id", "tenants"),
        ("prompt_set_revisions", "prompt_set_id", "prompt_sets"),
        ("prompt_set_revisions", "tenant_id", "tenants"),
    ):
        op.create_foreign_key(f"fk_{name}_{column}", name, target, [column], ["id"], ondelete="CASCADE")
    for name in ("tenant_prompts", "knowledge_bases", "tenant_prompt_revisions", "knowledge_base_revisions"):
        op.create_foreign_key(f"fk_{name}_tenant_id", name, "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_prompt_set_revisions_system", "prompt_set_revisions", "system_prompt_revisions", ["system_prompt_revision_id"], ["id"])
    op.create_foreign_key("fk_prompt_set_revisions_profile", "prompt_set_revisions", "profile_prompt_revisions", ["profile_prompt_revision_id"], ["id"])
    op.create_foreign_key("fk_prompt_set_revisions_tenant_prompt", "prompt_set_revisions", "tenant_prompt_revisions", ["tenant_id", "tenant_prompt_revision_id"], ["tenant_id", "id"])
    op.create_foreign_key("fk_prompt_set_revisions_knowledge", "prompt_set_revisions", "knowledge_base_revisions", ["tenant_id", "knowledge_base_revision_id"], ["tenant_id", "id"])
    op.add_column("tenants", sa.Column("active_prompt_set_revision_id", sa.Uuid()))
    op.add_column("call_sessions", sa.Column("prompt_set_revision_id", sa.Uuid()))
    op.create_table(
        "prompt_artifact_migration_map",
        sa.Column("old_bundle_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("new_prompt_set_revision_id", sa.Uuid(), nullable=False),
        sa.Column("old_config_revision_id", sa.Uuid(), nullable=True),
        sa.Column("new_config_revision_id", sa.Uuid(), nullable=True),
    )

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT * FROM prompt_bundle_revisions ORDER BY tenant_id, revision_number")).mappings()
    profile_id, profile_revision_id = uuid4(), uuid4()
    now = bind.execute(sa.text("SELECT now()")).scalar_one()
    bind.execute(sa.text("INSERT INTO profile_prompts (id, key) VALUES (:id, 'legacy_default')"), {"id": profile_id})
    bind.execute(sa.text("INSERT INTO profile_prompt_revisions (id, profile_prompt_id, revision_number, status, text, created_at, published_at, version) VALUES (:id, :parent, 1, 'published', '', :now, :now, 1)"), {"id": profile_revision_id, "parent": profile_id, "now": now})
    tenant_parents: dict[object, tuple[object, object, object]] = {}
    bundle_sets: dict[object, object] = {}
    for row in rows:
        tenant_id = row["tenant_id"]
        if tenant_id not in tenant_parents:
            tenant_prompt_id, knowledge_base_id, prompt_set_id = uuid4(), uuid4(), uuid4()
            tenant_parents[tenant_id] = (tenant_prompt_id, knowledge_base_id, prompt_set_id)
            bind.execute(sa.text("INSERT INTO tenant_prompts (id, tenant_id) VALUES (:id, :tenant)"), {"id": tenant_prompt_id, "tenant": tenant_id})
            bind.execute(sa.text("INSERT INTO knowledge_bases (id, tenant_id) VALUES (:id, :tenant)"), {"id": knowledge_base_id, "tenant": tenant_id})
            bind.execute(sa.text("INSERT INTO prompt_sets (id, tenant_id) VALUES (:id, :tenant)"), {"id": prompt_set_id, "tenant": tenant_id})
        tenant_prompt_id, knowledge_base_id, prompt_set_id = tenant_parents[tenant_id]
        system_id, system_revision_id = uuid4(), uuid4()
        tenant_revision_id, knowledge_revision_id, set_revision_id = uuid4(), uuid4(), uuid4()
        status = row["status"]
        artifact_status = "published" if status == "archived" else status
        published_at = row["published_at"]
        bind.execute(sa.text("INSERT INTO system_prompts (id, key) VALUES (:id, :key)"), {"id": system_id, "key": f"legacy_{tenant_id.hex}_{row['id'].hex}"})
        bind.execute(sa.text("INSERT INTO system_prompt_revisions (id, system_prompt_id, revision_number, status, text, created_at, published_at, version) VALUES (:id, :parent, 1, :status, :text, :created, :published, :version)"), {"id": system_revision_id, "parent": system_id, "status": artifact_status, "text": row["system_instructions"], "created": row["created_at"], "published": published_at, "version": row["version"]})
        for table, parent, revision_id, value in (("tenant_prompt_revisions", "tenant_prompt_id", tenant_revision_id, row["tenant_instructions"]), ("knowledge_base_revisions", "knowledge_base_id", knowledge_revision_id, row["knowledge_text"])):
            bind.execute(sa.text(f"INSERT INTO {table} (id, {parent}, tenant_id, revision_number, status, text, created_at, published_at, version) VALUES (:id, :parent, :tenant, :number, :status, :text, :created, :published, :version)"), {"id": revision_id, "parent": tenant_prompt_id if table.startswith("tenant") else knowledge_base_id, "tenant": tenant_id, "number": row["revision_number"], "status": artifact_status, "text": value, "created": row["created_at"], "published": published_at, "version": row["version"]})
        bind.execute(sa.text("INSERT INTO prompt_set_revisions (id, prompt_set_id, tenant_id, revision_number, status, system_prompt_revision_id, profile_prompt_revision_id, tenant_prompt_revision_id, knowledge_base_revision_id, created_at, published_at, version) VALUES (:id, :set, :tenant, :number, :status, :system, :profile, :tenant_prompt, :knowledge, :created, :published, :version)"), {"id": set_revision_id, "set": prompt_set_id, "tenant": tenant_id, "number": row["revision_number"], "status": status, "system": system_revision_id, "profile": profile_revision_id, "tenant_prompt": tenant_revision_id, "knowledge": knowledge_revision_id, "created": row["created_at"], "published": published_at, "version": row["version"]})
        bundle_sets[row["id"]] = set_revision_id
        bind.execute(sa.text("INSERT INTO prompt_artifact_migration_map (old_bundle_id, tenant_id, new_prompt_set_revision_id) VALUES (:bundle, :tenant, :set)"), {"bundle": row["id"], "tenant": tenant_id, "set": set_revision_id})
    for tenant_id, (_, _, prompt_set_id) in tenant_parents.items():
        active = bind.execute(sa.text("SELECT active_config_revision_id, display_name, business_type FROM tenants WHERE id = :id"), {"id": tenant_id}).mappings().one()
        if active["active_config_revision_id"] is None:
            continue
        config_row = bind.execute(sa.text("SELECT * FROM tenant_config_revisions WHERE id = :id"), {"id": active["active_config_revision_id"]}).mappings().one()
        if config_row["status"] != "published":
            raise RuntimeError(
                f"tenant {tenant_id} active config is not published; refusing migration"
            )
        config = deepcopy(config_row["config"])
        raw_bundle_id = config.get("prompt_bundle_revision_id")
        bundle_id = UUID(str(raw_bundle_id)) if raw_bundle_id else None
        if bundle_id not in bundle_sets:
            continue
        config.pop("prompt_bundle_revision_id", None)
        config["schema_version"] = 3
        config["business"] = {"name": active["display_name"], "type": active["business_type"]}
        config["contact"] = {}
        config["agent"] = {**config["agent"], "profile": "legacy_default"}
        new_id = uuid4()
        number = bind.execute(sa.text("SELECT COALESCE(MAX(revision_number), 0) + 1 FROM tenant_config_revisions WHERE tenant_id = :tenant"), {"tenant": tenant_id}).scalar_one()
        bind.execute(sa.text("INSERT INTO tenant_config_revisions (id, tenant_id, revision_number, schema_version, status, config, created_at, published_at, created_by, comment, version) VALUES (:id, :tenant, :number, 3, 'published', CAST(:config AS jsonb), :created, :published, :created_by, :comment, 1)"), {"id": new_id, "tenant": tenant_id, "number": number, "config": json.dumps(config), "created": now, "published": now, "created_by": config_row["created_by"], "comment": "Migrated to TenantConfigV3",})
        bind.execute(sa.text("UPDATE tenant_config_revisions SET status = 'archived' WHERE id = :id"), {"id": active["active_config_revision_id"]})
        bind.execute(sa.text("UPDATE tenants SET active_config_revision_id = :config, active_prompt_set_revision_id = :set WHERE id = :tenant"), {"config": new_id, "set": bundle_sets[bundle_id], "tenant": tenant_id})
        bind.execute(sa.text("UPDATE prompt_artifact_migration_map SET old_config_revision_id = :old, new_config_revision_id = :new WHERE tenant_id = :tenant AND old_bundle_id = :bundle"), {"old": active["active_config_revision_id"], "new": new_id, "tenant": tenant_id, "bundle": bundle_id})
    for bundle_id, set_id in bundle_sets.items():
        bind.execute(sa.text("UPDATE call_sessions SET prompt_set_revision_id = :set WHERE prompt_bundle_revision_id = :bundle"), {"set": set_id, "bundle": bundle_id})
    op.alter_column("call_sessions", "prompt_set_revision_id", nullable=False)
    op.create_foreign_key("fk_tenants_active_prompt_set_revision_same_tenant", "tenants", "prompt_set_revisions", ["id", "active_prompt_set_revision_id"], ["tenant_id", "id"])
    op.create_foreign_key("fk_call_sessions_prompt_set_revision_same_tenant", "call_sessions", "prompt_set_revisions", ["tenant_id", "prompt_set_revision_id"], ["tenant_id", "id"])


def downgrade() -> None:
    bind = op.get_bind()
    maps = list(bind.execute(sa.text("SELECT * FROM prompt_artifact_migration_map" )).mappings())
    expected = len(maps)
    for table in (
        "system_prompt_revisions",
        "tenant_prompt_revisions",
        "knowledge_base_revisions",
        "prompt_set_revisions",
    ):
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        if count != expected:
            raise RuntimeError(
                "prompt artifact downgrade is guarded: post-migration revisions exist"
            )
    profile_count = bind.execute(
        sa.text("SELECT count(*) FROM profile_prompt_revisions")
    ).scalar_one()
    if profile_count != 1:
        raise RuntimeError(
            "prompt artifact downgrade is guarded: profile revisions changed"
        )
    expected_v3 = bind.execute(
        sa.text(
            "SELECT count(*) FROM prompt_artifact_migration_map "
            "WHERE new_config_revision_id IS NOT NULL"
        )
    ).scalar_one()
    actual_v3 = bind.execute(
        sa.text("SELECT count(*) FROM tenant_config_revisions WHERE schema_version = 3")
    ).scalar_one()
    if actual_v3 != expected_v3:
        raise RuntimeError(
            "prompt artifact downgrade is guarded: TenantConfigV3 revisions changed"
        )
    for item in maps:
        bind.execute(sa.text("UPDATE call_sessions SET prompt_bundle_revision_id = :old WHERE prompt_set_revision_id = :new"), {"old": item["old_bundle_id"], "new": item["new_prompt_set_revision_id"]})
    for item in maps:
        if item["old_config_revision_id"] is not None:
            bind.execute(sa.text("UPDATE tenants SET active_config_revision_id = :old, active_prompt_set_revision_id = NULL WHERE active_config_revision_id = :new"), {"old": item["old_config_revision_id"], "new": item["new_config_revision_id"]})
            bind.execute(sa.text("UPDATE tenant_config_revisions SET status = 'published' WHERE id = :old"), {"old": item["old_config_revision_id"]})
            bind.execute(sa.text("DELETE FROM tenant_config_revisions WHERE id = :new"), {"new": item["new_config_revision_id"]})
    op.drop_table("prompt_artifact_migration_map")
    op.drop_constraint("fk_call_sessions_prompt_set_revision_same_tenant", "call_sessions", type_="foreignkey")
    op.drop_column("call_sessions", "prompt_set_revision_id")
    op.drop_constraint("fk_tenants_active_prompt_set_revision_same_tenant", "tenants", type_="foreignkey")
    op.drop_column("tenants", "active_prompt_set_revision_id")
    for name, parent in (("prompt_set_revisions", "prompt_set_id"), ("knowledge_base_revisions", "knowledge_base_id"), ("tenant_prompt_revisions", "tenant_prompt_id"), ("profile_prompt_revisions", "profile_prompt_id"), ("system_prompt_revisions", "system_prompt_id")):
        op.drop_index(f"uq_{name}_one_draft", table_name=name, postgresql_where=sa.text("status = 'draft'"))
        op.drop_table(name)
    for name in ("prompt_sets", "knowledge_bases", "tenant_prompts", "profile_prompts", "system_prompts"):
        op.drop_table(name)
    prompt_status.drop(op.get_bind(), checkfirst=True)
