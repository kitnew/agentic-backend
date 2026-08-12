"""Persist the outbound SIP participant created for a room handoff."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0025"
down_revision: str | None = "20260812_0024"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "call_sessions",
        sa.Column("handoff_participant_identity", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "call_sessions",
        sa.Column("handoff_sip_call_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    # Transport diagnostics are discarded; the call and handoff remain valid.
    op.drop_column("call_sessions", "handoff_sip_call_id")
    op.drop_column("call_sessions", "handoff_participant_identity")
