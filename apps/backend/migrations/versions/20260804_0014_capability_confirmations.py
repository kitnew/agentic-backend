"""add backend-owned capability confirmation snapshots

Revision ID: 20260804_0014
Revises: 20260804_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0014"
down_revision: str | None = "20260804_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capability_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=255), nullable=False),
        sa.Column("semantic_key", sa.String(length=128), nullable=False),
        sa.Column("semantic_version", sa.Integer(), nullable=False),
        sa.Column("tenant_config_revision_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_input", sa.JSON(), nullable=False),
        sa.Column("agent_input", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("invocation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending_confirmation",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_capability_confirmations_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "call_id"],
            ["call_sessions.tenant_id", "call_sessions.id"],
            name="fk_capability_confirmations_call_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tenant_config_revision_id"],
            ["tenant_config_revisions.tenant_id", "tenant_config_revisions.id"],
            name="fk_capability_confirmations_config_same_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "call_id",
            "tool_call_id",
            name="uq_capability_confirmations_call_tool",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_capability_confirmations_expires_at",
        "capability_confirmations",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_capability_confirmations_expires_at", table_name="capability_confirmations"
    )
    op.drop_table("capability_confirmations")
