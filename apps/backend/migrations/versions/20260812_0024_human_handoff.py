"""Persist successful human handoff operation identity."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0024"
down_revision: str | None = "20260811_0023"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "call_sessions",
        sa.Column("handoff_tool_call_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "call_sessions",
        sa.Column("handoff_destination", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    # Successful handoff diagnostics are discarded; the call lifecycle remains.
    op.drop_column("call_sessions", "handoff_destination")
    op.drop_column("call_sessions", "handoff_tool_call_id")
