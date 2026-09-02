"""Allow the current execution snapshot schema version."""

import sqlalchemy as sa
from alembic import op


revision = "0002_snapshot_schema_v2"
down_revision = "0001_initial_control_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_execution_snapshot_schema_version",
        "execution_snapshots",
        schema="control_plane",
        type_="check",
    )
    op.create_check_constraint(
        "ck_execution_snapshot_schema_version",
        "execution_snapshots",
        sa.text("schema_version IN (1, 2)"),
        schema="control_plane",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_execution_snapshot_schema_version",
        "execution_snapshots",
        schema="control_plane",
        type_="check",
    )
    op.create_check_constraint(
        "ck_execution_snapshot_schema_version",
        "execution_snapshots",
        sa.text("schema_version = 1"),
        schema="control_plane",
    )
