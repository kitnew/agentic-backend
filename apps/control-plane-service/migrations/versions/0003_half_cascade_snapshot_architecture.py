"""Allow half-cascade execution snapshots.

Revision ID: 0003_half_cascade_architecture
Revises: 0002_snapshot_schema_v3
"""

from alembic import op

revision = "0003_half_cascade_architecture"
down_revision = "0002_snapshot_schema_v3"
branch_labels = None
depends_on = None
SCHEMA = "control_plane"


def upgrade() -> None:
    op.drop_constraint(
        "ck_execution_snapshot_architecture",
        "execution_snapshots",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_execution_snapshot_architecture",
        "execution_snapshots",
        "architecture IN ('cascade', 'realtime', 'half-cascade')",
        schema=SCHEMA,
    )
    # Preserve the configured realtime-transcription deployment name as the
    # explicit API model value; no provider model is invented here.
    op.execute(
        """
        UPDATE control_plane.model_deployments AS d
        SET deployment_config = jsonb_set(
            COALESCE(d.deployment_config, '{}'::jsonb),
            '{model}',
            d.deployment_config -> 'deployment_name',
            true
        )
        WHERE d.deployment_kind = 'stt'
          AND COALESCE(d.capabilities ->> 'supports_realtime_input_transcription', 'false') = 'true'
          AND d.deployment_config ->> 'model' IS NULL
          AND d.deployment_config ->> 'deployment_name' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_execution_snapshot_architecture",
        "execution_snapshots",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_execution_snapshot_architecture",
        "execution_snapshots",
        "architecture IN ('cascade', 'realtime')",
        schema=SCHEMA,
    )
