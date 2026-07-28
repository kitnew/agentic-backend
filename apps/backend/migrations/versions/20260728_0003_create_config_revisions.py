"""Create versioned tenant configuration.

Revision ID: 20260728_0003
Revises: 20260728_0002
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0003"
down_revision: str | None = "20260728_0002"
branch_labels: str | None = None
depends_on: str | None = None

config_revision_status = postgresql.ENUM(
    "draft",
    "published",
    "archived",
    name="config_revision_status",
)


def upgrade() -> None:
    op.create_table(
        "tenant_config_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            config_revision_status,
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_tenant_config_revisions_revision_number_positive",
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_tenant_config_revisions_schema_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_config_revisions_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_config_revisions"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_tenant_config_revisions_tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "revision_number",
            name="uq_tenant_config_revisions_tenant_revision",
        ),
    )
    op.create_index(
        "uq_tenant_config_revisions_one_draft",
        "tenant_config_revisions",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.add_column(
        "tenants",
        sa.Column("active_config_revision_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tenants_active_config_revision_same_tenant",
        "tenants",
        "tenant_config_revisions",
        ["id", "active_config_revision_id"],
        ["tenant_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tenants_active_config_revision_same_tenant",
        "tenants",
        type_="foreignkey",
    )
    op.drop_column("tenants", "active_config_revision_id")
    op.drop_index(
        "uq_tenant_config_revisions_one_draft",
        table_name="tenant_config_revisions",
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.drop_table("tenant_config_revisions")
    config_revision_status.drop(op.get_bind(), checkfirst=True)
