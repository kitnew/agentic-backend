"""Add authoritative call lifecycle and distributed messaging foundation."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0021"
down_revision: str | None = "20260810_0020"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "call_sessions",
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint(
        "ck_call_sessions_lifecycle_fields", "call_sessions", type_="check"
    )
    op.execute("ALTER TABLE call_sessions ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "CREATE TYPE call_session_status_next AS ENUM "
        "('created', 'started', 'connected', 'ended', 'failed')"
    )
    op.execute(
        "ALTER TABLE call_sessions ALTER COLUMN status TYPE "
        "call_session_status_next USING "
        "(CASE status::text "
        "WHEN 'active' THEN 'connected' "
        "WHEN 'completed' THEN 'ended' "
        "ELSE status::text END)::call_session_status_next"
    )
    op.execute("DROP TYPE call_session_status")
    op.execute("ALTER TYPE call_session_status_next RENAME TO call_session_status")
    op.execute("ALTER TABLE call_sessions ALTER COLUMN status SET DEFAULT 'created'")
    op.execute(
        "UPDATE call_sessions SET connected_at = started_at "
        "WHERE status IN ('connected', 'ended')"
    )
    op.create_check_constraint(
        "ck_call_sessions_lifecycle_fields",
        "call_sessions",
        """
        (status = 'created' AND started_at IS NULL AND ended_at IS NULL
            AND failure_reason IS NULL)
        OR (status = 'started' AND started_at IS NOT NULL
            AND connected_at IS NULL AND ended_at IS NULL
            AND failure_reason IS NULL)
        OR (status = 'connected' AND started_at IS NOT NULL
            AND connected_at IS NOT NULL AND ended_at IS NULL
            AND failure_reason IS NULL)
        OR (status = 'ended' AND started_at IS NOT NULL
            AND connected_at IS NOT NULL AND ended_at IS NOT NULL
            AND failure_reason IS NULL)
        OR (status = 'failed' AND ended_at IS NOT NULL
            AND failure_reason IS NOT NULL)
        """,
    )

    op.alter_column("outbox_messages", "capability_invocation_id", nullable=True)
    op.add_column(
        "outbox_messages",
        sa.Column("stream", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "outbox_messages",
        sa.Column(
            "payload_field", sa.String(length=32), server_default="job", nullable=False
        ),
    )

    finalization_status = postgresql.ENUM(
        "pending",
        "processing",
        "completed",
        "failed",
        name="call_finalization_status",
        create_type=False,
    )
    finalization_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "call_finalizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("status", finalization_status, server_default="pending", nullable=False),
        sa.Column(
            "action_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("next_action_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("current_command_id", sa.Uuid(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["call_id"], ["call_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_id"),
    )
    op.create_index(
        "ix_call_finalizations_current_command_id",
        "call_finalizations",
        ["current_command_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_call_finalizations_current_command_id", table_name="call_finalizations"
    )
    op.drop_table("call_finalizations")
    postgresql.ENUM(name="call_finalization_status").drop(
        op.get_bind(), checkfirst=True
    )
    op.drop_column("outbox_messages", "payload_field")
    op.drop_column("outbox_messages", "stream")
    op.execute(
        "DELETE FROM outbox_messages WHERE capability_invocation_id IS NULL"
    )
    op.alter_column("outbox_messages", "capability_invocation_id", nullable=False)

    op.drop_constraint(
        "ck_call_sessions_lifecycle_fields", "call_sessions", type_="check"
    )
    op.execute("ALTER TABLE call_sessions ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "CREATE TYPE call_session_status_previous AS ENUM "
        "('created', 'active', 'completed', 'failed')"
    )
    op.execute(
        "ALTER TABLE call_sessions ALTER COLUMN status TYPE "
        "call_session_status_previous USING "
        "(CASE status::text "
        "WHEN 'started' THEN 'active' "
        "WHEN 'connected' THEN 'active' "
        "WHEN 'ended' THEN 'completed' "
        "ELSE status::text END)::call_session_status_previous"
    )
    op.execute("DROP TYPE call_session_status")
    op.execute(
        "ALTER TYPE call_session_status_previous RENAME TO call_session_status"
    )
    op.execute(
        "ALTER TABLE call_sessions ALTER COLUMN status SET DEFAULT 'created'"
    )
    op.drop_column("call_sessions", "connected_at")
    op.create_check_constraint(
        "ck_call_sessions_lifecycle_fields",
        "call_sessions",
        """
        (status = 'created' AND started_at IS NULL AND ended_at IS NULL
            AND failure_reason IS NULL)
        OR (status = 'active' AND started_at IS NOT NULL AND ended_at IS NULL
            AND failure_reason IS NULL)
        OR (status = 'completed' AND started_at IS NOT NULL
            AND ended_at IS NOT NULL AND failure_reason IS NULL)
        OR (status = 'failed' AND ended_at IS NOT NULL
            AND failure_reason IS NOT NULL)
        """,
    )
