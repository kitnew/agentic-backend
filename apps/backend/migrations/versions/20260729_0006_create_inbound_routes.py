"""Create inbound tenant routes.

Revision ID: 20260729_0006
Revises: 20260729_0005
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0006"
down_revision: str | None = "20260729_0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "inbound_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_did", sa.String(length=16), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
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
            "normalized_did ~ '^\\+[1-9][0-9]{1,14}$'",
            name="ck_inbound_routes_normalized_did_e164",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_inbound_routes_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "normalized_did",
            name="uq_inbound_routes_normalized_did",
        ),
    )
    op.create_index(
        "ix_inbound_routes_tenant_id",
        "inbound_routes",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_inbound_routes_tenant_id", table_name="inbound_routes")
    op.drop_table("inbound_routes")
