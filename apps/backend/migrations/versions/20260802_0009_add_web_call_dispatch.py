"""Add web calls and provider dispatch references.

Revision ID: 20260802_0009
Revises: 20260729_0008
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0009"
down_revision: str | None = "20260729_0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE call_channel ADD VALUE IF NOT EXISTS 'web'")
    op.add_column(
        "call_sessions",
        sa.Column("provider_dispatch_id", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_call_sessions_provider_dispatch_id",
        "call_sessions",
        ["provider", "provider_dispatch_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_call_sessions_provider_dispatch_id",
        "call_sessions",
        type_="unique",
    )
    op.drop_column("call_sessions", "provider_dispatch_id")
    op.execute(
        "ALTER TABLE call_sessions ALTER COLUMN channel TYPE varchar(16) "
        "USING channel::text"
    )
    op.execute("UPDATE call_sessions SET channel = 'sip' WHERE channel = 'web'")
    op.execute("DROP TYPE call_channel")
    op.execute("CREATE TYPE call_channel AS ENUM ('sip')")
    op.execute(
        "ALTER TABLE call_sessions ALTER COLUMN channel TYPE call_channel "
        "USING channel::call_channel"
    )
