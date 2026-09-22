"""Persist the correlated human handoff lifecycle."""

import sqlalchemy as sa
from alembic import op

revision = "0002_handoff_lifecycle"
down_revision = "0001_initial_backend"
branch_labels = None
depends_on = None

handoff_state = sa.Enum(
    "dialing",
    "answered",
    "completed",
    "failed",
    "timed_out",
    "canceled",
    name="handoff_state",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("call_sessions")}
    handoff_state.create(bind, checkfirst=True)
    if "handoff_attempt_id" not in columns:
        op.add_column(
            "call_sessions", sa.Column("handoff_attempt_id", sa.Uuid(), nullable=True)
        )
    if "handoff_state" not in columns:
        op.add_column(
            "call_sessions", sa.Column("handoff_state", handoff_state, nullable=True)
        )
    constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("call_sessions")
    }
    if "ck_call_sessions_handoff_attempt_fields" not in constraints:
        op.create_check_constraint(
            "ck_call_sessions_handoff_attempt_fields",
            "call_sessions",
            "(handoff_attempt_id IS NULL AND handoff_state IS NULL) OR "
            "(handoff_attempt_id IS NOT NULL AND handoff_state IS NOT NULL)",
        )


def downgrade() -> None:
    op.drop_constraint(
        "ck_call_sessions_handoff_attempt_fields",
        "call_sessions",
        type_="check",
    )
    op.drop_column("call_sessions", "handoff_state")
    op.drop_column("call_sessions", "handoff_attempt_id")
    handoff_state.drop(op.get_bind(), checkfirst=True)
