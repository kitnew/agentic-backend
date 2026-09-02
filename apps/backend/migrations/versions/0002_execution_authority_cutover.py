"""Pin newly created calls to a Control Plane execution snapshot."""

from alembic import op
import sqlalchemy as sa

revision = "0002_execution_authority_cutover"
down_revision = "0001_initial_backend"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "call_sessions",
        sa.Column("execution_snapshot_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "capability_invocations",
        sa.Column("execution_snapshot_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "capability_confirmations",
        sa.Column("execution_snapshot_id", sa.Uuid(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("capability_confirmations", "execution_snapshot_id")
    op.drop_column("capability_invocations", "execution_snapshot_id")
    op.drop_column("call_sessions", "execution_snapshot_id")
