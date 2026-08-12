"""Move canonical call recordings from PostgreSQL bytes to LiveKit Egress objects."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0026"
down_revision: str | None = "20260812_0025"
branch_labels: str | None = None
depends_on: str | None = None


def _require_empty_legacy_recordings() -> None:
    bind = op.get_bind()
    recordings = bind.scalar(sa.text("SELECT count(*) FROM call_recordings"))
    representations = bind.scalar(
        sa.text(
            "SELECT count(*) FROM artifact_representations "
            "WHERE artifact_type = 'call_recording'"
        )
    )
    if recordings or representations:
        raise RuntimeError(
            "export legacy PostgreSQL recording bytes before this migration"
        )


def upgrade() -> None:
    _require_empty_legacy_recordings()
    status = postgresql.ENUM(
        "pending",
        "recording",
        "ready",
        "failed",
        name="call_recording_status",
        create_type=False,
    )
    status.create(op.get_bind(), checkfirst=True)
    op.drop_constraint(
        "fk_call_recordings_call_same_tenant", "call_recordings", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_call_recordings_call_same_tenant",
        "call_recordings",
        "call_sessions",
        ["tenant_id", "call_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "ck_call_recordings_byte_size_positive", "call_recordings", type_="check"
    )
    op.drop_column("call_recordings", "content")
    op.drop_column("call_recordings", "sha256")
    op.add_column(
        "call_recordings",
        sa.Column(
            "provider",
            sa.String(length=64),
            server_default="livekit_egress",
            nullable=False,
        ),
    )
    op.add_column(
        "call_recordings", sa.Column("egress_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "call_recordings",
        sa.Column("status", status, server_default="pending", nullable=False),
    )
    op.add_column(
        "call_recordings",
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
    )
    op.alter_column(
        "call_recordings", "content_type", server_default="audio/mpeg", nullable=False
    )
    op.alter_column("call_recordings", "byte_size", nullable=True)
    op.add_column(
        "call_recordings", sa.Column("duration_ms", sa.Integer(), nullable=True)
    )
    op.add_column(
        "call_recordings",
        sa.Column(
            "start_requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "call_recordings",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "call_recordings",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "call_recordings",
        sa.Column("error_code", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "call_recordings",
        sa.Column("error_detail", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "call_recordings",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_call_recordings_egress_id", "call_recordings", ["egress_id"]
    )
    op.create_unique_constraint(
        "uq_call_recordings_storage_key", "call_recordings", ["storage_key"]
    )
    op.create_check_constraint(
        "ck_call_recordings_lifecycle",
        "call_recordings",
        "(status = 'ready' AND egress_id IS NOT NULL AND byte_size > 0 "
        "AND duration_ms >= 0 AND completed_at IS NOT NULL AND error_code IS NULL) "
        "OR (status = 'failed' AND error_code IS NOT NULL "
        "AND completed_at IS NOT NULL) "
        "OR (status = 'recording' AND egress_id IS NOT NULL "
        "AND started_at IS NOT NULL AND completed_at IS NULL) "
        "OR (status = 'pending' AND completed_at IS NULL)",
    )
    op.drop_constraint(
        "ck_artifact_representations_completed_content",
        "artifact_representations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_artifact_representations_completed_content",
        "artifact_representations",
        "(status = 'completed' AND byte_size IS NOT NULL "
        "AND completed_at IS NOT NULL AND "
        "((artifact_type = 'call_recording' AND content IS NULL) OR "
        "(content IS NOT NULL AND sha256 IS NOT NULL))) "
        "OR (status <> 'completed')",
    )


def downgrade() -> None:
    _require_empty_legacy_recordings()
    op.drop_constraint(
        "fk_call_recordings_call_same_tenant", "call_recordings", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_call_recordings_call_same_tenant",
        "call_recordings",
        "call_sessions",
        ["tenant_id", "call_id"],
        ["tenant_id", "id"],
    )
    op.drop_constraint(
        "ck_artifact_representations_completed_content",
        "artifact_representations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_artifact_representations_completed_content",
        "artifact_representations",
        "(status = 'completed' AND content IS NOT NULL AND byte_size IS NOT NULL "
        "AND sha256 IS NOT NULL AND completed_at IS NOT NULL) "
        "OR (status <> 'completed')",
    )
    op.drop_constraint(
        "ck_call_recordings_lifecycle", "call_recordings", type_="check"
    )
    op.drop_constraint(
        "uq_call_recordings_storage_key", "call_recordings", type_="unique"
    )
    op.drop_constraint(
        "uq_call_recordings_egress_id", "call_recordings", type_="unique"
    )
    for column in (
        "updated_at",
        "error_detail",
        "error_code",
        "completed_at",
        "started_at",
        "start_requested_at",
        "duration_ms",
        "storage_key",
        "status",
        "egress_id",
        "provider",
    ):
        op.drop_column("call_recordings", column)
    op.alter_column("call_recordings", "byte_size", nullable=False)
    op.alter_column("call_recordings", "content_type", server_default=None)
    op.add_column(
        "call_recordings", sa.Column("content", sa.LargeBinary(), nullable=False)
    )
    op.add_column(
        "call_recordings", sa.Column("sha256", sa.String(length=64), nullable=False)
    )
    op.create_check_constraint(
        "ck_call_recordings_byte_size_positive", "call_recordings", "byte_size > 0"
    )
    postgresql.ENUM(name="call_recording_status").drop(
        op.get_bind(), checkfirst=True
    )
