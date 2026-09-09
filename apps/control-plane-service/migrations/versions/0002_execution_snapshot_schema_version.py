"""Align execution snapshot schema version with the runtime contract.

Revision ID: 0002_snapshot_schema_v3
Revises: 0001_initial_control_plane
"""

from alembic import op

revision = "0002_snapshot_schema_v3"
down_revision = "0001_initial_control_plane"
branch_labels = None
depends_on = None
SCHEMA = "control_plane"


def upgrade() -> None:
    op.drop_constraint(
        "ck_execution_snapshot_schema_version",
        "execution_snapshots",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_execution_snapshot_schema_version",
        "execution_snapshots",
        "schema_version = 3",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_execution_snapshot_schema_version",
        "execution_snapshots",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_execution_snapshot_schema_version",
        "execution_snapshots",
        "schema_version = 2",
        schema=SCHEMA,
    )
