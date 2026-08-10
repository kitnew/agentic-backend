"""Add versioned voice runtime authoring and effective call pins.

Revision ID: 20260810_0020
Revises: 20260810_0019
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260810_0020"
down_revision = "20260810_0019"
branch_labels = None
depends_on = None


runtime_status = postgresql.ENUM(
    "draft", "published", "archived", name="runtime_revision_status"
)
runtime_status_column = postgresql.ENUM(
    "draft",
    "published",
    "archived",
    name="runtime_revision_status",
    create_type=False,
)


def upgrade() -> None:
    runtime_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "platform_runtimes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
    )
    op.create_table(
        "platform_runtime_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("platform_runtime_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            runtime_status_column,
            nullable=False,
            server_default="draft",
        ),
        sa.Column("policy", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["platform_runtime_id"], ["platform_runtimes.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("platform_runtime_id", "revision_number"),
        sa.CheckConstraint("revision_number > 0"),
        sa.CheckConstraint("version > 0"),
    )
    op.create_index(
        "uq_platform_runtime_revisions_one_draft",
        "platform_runtime_revisions",
        ["platform_runtime_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_table(
        "tenant_runtimes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_table(
        "tenant_runtime_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_runtime_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            runtime_status_column,
            nullable=False,
            server_default="draft",
        ),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tenant_runtime_id"],
            ["tenant_runtimes.tenant_id", "tenant_runtimes.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_runtime_id", "revision_number"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.CheckConstraint("revision_number > 0"),
        sa.CheckConstraint("version > 0"),
    )
    op.create_index(
        "uq_tenant_runtime_revisions_one_draft",
        "tenant_runtime_revisions",
        ["tenant_runtime_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_table(
        "voice_runtimes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id"),
        sa.UniqueConstraint("tenant_id", "id"),
    )
    op.create_table(
        "voice_runtime_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("voice_runtime_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            runtime_status_column,
            nullable=False,
            server_default="published",
        ),
        sa.Column("platform_runtime_revision_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_runtime_revision_id", sa.Uuid()),
        sa.Column("effective_settings", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "voice_runtime_id"],
            ["voice_runtimes.tenant_id", "voice_runtimes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["platform_runtime_revision_id"], ["platform_runtime_revisions.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tenant_runtime_revision_id"],
            ["tenant_runtime_revisions.tenant_id", "tenant_runtime_revisions.id"],
        ),
        sa.UniqueConstraint("voice_runtime_id", "revision_number"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.CheckConstraint("revision_number > 0"),
    )
    op.add_column("tenants", sa.Column("active_voice_runtime_revision_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_tenants_active_voice_runtime_revision_same_tenant",
        "tenants",
        "voice_runtime_revisions",
        ["id", "active_voice_runtime_revision_id"],
        ["tenant_id", "id"],
        use_alter=True,
    )
    op.add_column("call_sessions", sa.Column("voice_runtime_revision_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_call_sessions_voice_runtime_revision_same_tenant",
        "call_sessions",
        "voice_runtime_revisions",
        ["tenant_id", "voice_runtime_revision_id"],
        ["tenant_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_call_sessions_voice_runtime_revision_same_tenant",
        "call_sessions",
        type_="foreignkey",
    )
    op.drop_column("call_sessions", "voice_runtime_revision_id")
    op.drop_constraint(
        "fk_tenants_active_voice_runtime_revision_same_tenant",
        "tenants",
        type_="foreignkey",
    )
    op.drop_column("tenants", "active_voice_runtime_revision_id")
    op.drop_table("voice_runtime_revisions")
    op.drop_table("voice_runtimes")
    op.drop_index(
        "uq_tenant_runtime_revisions_one_draft",
        table_name="tenant_runtime_revisions",
    )
    op.drop_table("tenant_runtime_revisions")
    op.drop_table("tenant_runtimes")
    op.drop_index(
        "uq_platform_runtime_revisions_one_draft",
        table_name="platform_runtime_revisions",
    )
    op.drop_table("platform_runtime_revisions")
    op.drop_table("platform_runtimes")
    runtime_status.drop(op.get_bind(), checkfirst=True)
