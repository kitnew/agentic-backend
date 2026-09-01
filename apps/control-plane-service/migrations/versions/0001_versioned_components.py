"""versioned configuration components

Revision ID: 0001_versioned_components
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_versioned_components"
down_revision = None
branch_labels = None
depends_on = None
SCHEMA = "control_plane"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.create_table(
        "configuration_components",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(255), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_key", sa.String(255)),
        sa.Column("active_revision_id", sa.Uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(scope_type = 'platform' AND scope_key IS NULL) OR (scope_type IN ('tenant', 'profile') AND scope_key IS NOT NULL AND scope_key <> '')",
            name="ck_configuration_component_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_configuration_component_address",
        "configuration_components",
        ["kind", "scope_type", "scope_key"],
        unique=True,
        schema=SCHEMA,
        postgresql_nulls_not_distinct=True,
    )
    op.create_table(
        "configuration_component_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "component_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.configuration_components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "based_on_revision_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.configuration_component_revisions.id"),
        ),
        sa.Column(
            "restored_from_revision_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.configuration_component_revisions.id"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.CheckConstraint(
            "revision_number >= 1", name="ck_configuration_component_revision_number"
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_configuration_component_revision_schema_version",
        ),
        sa.UniqueConstraint(
            "component_id",
            "revision_number",
            name="uq_configuration_component_revision_number",
        ),
        sa.UniqueConstraint(
            "id", "component_id", name="uq_configuration_component_revision_identity"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "configuration_component_drafts",
        sa.Column(
            "component_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.configuration_components.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "based_on_revision_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.configuration_component_revisions.id"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_configuration_component_draft_schema_version",
        ),
        sa.CheckConstraint(
            "version >= 1", name="ck_configuration_component_draft_version"
        ),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_configuration_component_active_revision",
        "configuration_components",
        "configuration_component_revisions",
        ["active_revision_id", "id"],
        ["id", "component_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_configuration_component_active_revision",
        "configuration_components",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_table("configuration_component_drafts", schema=SCHEMA)
    op.drop_table("configuration_component_revisions", schema=SCHEMA)
    op.drop_index(
        "uq_configuration_component_address",
        table_name="configuration_components",
        schema=SCHEMA,
    )
    op.drop_table("configuration_components", schema=SCHEMA)
    op.execute(f"DROP SCHEMA {SCHEMA}")
