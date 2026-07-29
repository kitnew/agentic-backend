"""Create versioned prompt bundle storage.

Revision ID: 20260729_0007
Revises: 20260729_0006
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0007"
down_revision: str | None = "20260729_0006"
branch_labels: str | None = None
depends_on: str | None = None

prompt_bundle_revision_status = postgresql.ENUM(
    "draft",
    "published",
    "archived",
    name="prompt_bundle_revision_status",
)


def upgrade() -> None:
    op.create_table(
        "prompt_bundle_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            prompt_bundle_revision_status,
            server_default="draft",
            nullable=False,
        ),
        sa.Column("system_instructions", sa.Text(), nullable=False),
        sa.Column("tenant_instructions", sa.Text(), nullable=False),
        sa.Column("knowledge_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_prompt_bundle_revisions_revision_number_positive",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_prompt_bundle_revisions_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_prompt_bundle_revisions_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_bundle_revisions"),
        sa.UniqueConstraint(
            "tenant_id",
            "revision_number",
            name="uq_prompt_bundle_revisions_tenant_revision",
        ),
    )
    op.create_index(
        "uq_prompt_bundle_revisions_one_draft",
        "prompt_bundle_revisions",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_prompt_bundle_revisions_one_draft",
        table_name="prompt_bundle_revisions",
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.drop_table("prompt_bundle_revisions")
    prompt_bundle_revision_status.drop(op.get_bind(), checkfirst=True)
