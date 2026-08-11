"""Add declarative post-call action and artifact execution state."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0022"
down_revision: str | None = "20260811_0021"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    work_status = postgresql.ENUM(
        "pending",
        "processing",
        "completed",
        "failed",
        name="post_call_work_status",
        create_type=False,
    )
    work_status.create(op.get_bind(), checkfirst=True)
    op.alter_column(
        "call_finalizations",
        "current_command_id",
        new_column_name="summary_command_id",
    )
    op.drop_index(
        "ix_call_finalizations_current_command_id", table_name="call_finalizations"
    )
    op.create_index(
        "ix_call_finalizations_summary_command_id",
        "call_finalizations",
        ["summary_command_id"],
    )
    op.create_table(
        "post_call_action_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("finalization_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.String(length=128), nullable=False),
        sa.Column("status", work_status, server_default="pending", nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["finalization_id"], ["call_finalizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "finalization_id",
            "action_id",
            name="uq_post_call_action_execution_logical_action",
        ),
        sa.UniqueConstraint(
            "command_id", name="uq_post_call_action_execution_command_id"
        ),
    )
    op.create_index(
        "ix_post_call_action_executions_finalization_id",
        "post_call_action_executions",
        ["finalization_id"],
    )
    op.create_index(
        "ix_post_call_action_executions_command_id",
        "post_call_action_executions",
        ["command_id"],
    )
    op.execute(
        """
        INSERT INTO post_call_action_executions
            (id, finalization_id, action_id, status, command_id, last_error,
             created_at, completed_at)
        SELECT gen_random_uuid(), f.id, action.value,
            CASE
                WHEN f.status = 'completed' OR action.ordinality - 1 < f.next_action_index
                    THEN 'completed'::post_call_work_status
                WHEN f.status = 'failed' AND f.summary IS NOT NULL
                     AND action.ordinality - 1 = f.next_action_index
                    THEN 'failed'::post_call_work_status
                WHEN f.status = 'processing' AND f.summary IS NOT NULL
                     AND action.ordinality - 1 = f.next_action_index
                    THEN 'processing'::post_call_work_status
                ELSE 'pending'::post_call_work_status
            END,
            CASE
                WHEN f.status = 'processing' AND f.summary IS NOT NULL
                     AND action.ordinality - 1 = f.next_action_index
                    THEN f.summary_command_id
                ELSE NULL
            END,
            CASE
                WHEN f.status = 'failed' AND f.summary IS NOT NULL
                     AND action.ordinality - 1 = f.next_action_index
                    THEN f.last_error
                ELSE NULL
            END,
            f.created_at,
            CASE
                WHEN f.status = 'completed' OR action.ordinality - 1 < f.next_action_index
                    THEN f.completed_at
                ELSE NULL
            END
        FROM call_finalizations AS f,
             jsonb_array_elements_text(f.action_ids) WITH ORDINALITY AS action(value, ordinality)
        """
    )
    op.execute(
        "UPDATE call_finalizations SET summary_command_id = NULL WHERE summary IS NOT NULL"
    )
    op.drop_column("call_finalizations", "next_action_index")
    op.drop_column("call_finalizations", "action_ids")

    op.create_table(
        "call_recordings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "byte_size > 0", name="ck_call_recordings_byte_size_positive"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "call_id"],
            ["call_sessions.tenant_id", "call_sessions.id"],
            name="fk_call_recordings_call_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("call_id", name="uq_call_recordings_call_id"),
    )
    op.create_table(
        "artifact_representations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("representation", sa.String(length=64), nullable=False),
        sa.Column("status", work_status, server_default="processing", nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(artifact_type = 'transcript' AND representation = 'plain_text') "
            "OR (artifact_type = 'call_recording' AND representation = 'base64_text')",
            name="ck_artifact_representations_materializable_kind",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND content IS NOT NULL AND byte_size IS NOT NULL "
            "AND sha256 IS NOT NULL AND completed_at IS NOT NULL) "
            "OR (status <> 'completed')",
            name="ck_artifact_representations_completed_content",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "call_id"],
            ["call_sessions.tenant_id", "call_sessions.id"],
            name="fk_artifact_representations_call_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "command_id", name="uq_artifact_representations_command_id"
        ),
        sa.UniqueConstraint(
            "call_id",
            "artifact_type",
            "representation",
            name="uq_artifact_representations_call_kind",
        ),
    )
    op.create_index(
        "ix_artifact_representations_command_id",
        "artifact_representations",
        ["command_id"],
    )


def downgrade() -> None:
    op.add_column(
        "call_finalizations",
        sa.Column(
            "action_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.add_column(
        "call_finalizations",
        sa.Column(
            "next_action_index", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.execute(
        """
        UPDATE call_finalizations AS f SET
            action_ids = state.action_ids,
            next_action_index = state.completed_count,
            summary_command_id = CASE
                WHEN f.summary IS NULL THEN f.summary_command_id
                ELSE state.current_command_id
            END
        FROM (
            SELECT finalization_id,
                   jsonb_agg(action_id ORDER BY created_at, action_id) AS action_ids,
                   count(*) FILTER (WHERE status = 'completed') AS completed_count,
                   (array_agg(command_id) FILTER (WHERE status = 'processing'))[1]
                       AS current_command_id
            FROM post_call_action_executions
            GROUP BY finalization_id
        ) AS state
        WHERE f.id = state.finalization_id
        """
    )
    op.drop_index(
        "ix_artifact_representations_command_id",
        table_name="artifact_representations",
    )
    op.drop_table("artifact_representations")
    op.drop_table("call_recordings")
    op.drop_index(
        "ix_post_call_action_executions_command_id",
        table_name="post_call_action_executions",
    )
    op.drop_index(
        "ix_post_call_action_executions_finalization_id",
        table_name="post_call_action_executions",
    )
    op.drop_table("post_call_action_executions")
    postgresql.ENUM(name="post_call_work_status").drop(op.get_bind(), checkfirst=True)
    op.drop_index(
        "ix_call_finalizations_summary_command_id", table_name="call_finalizations"
    )
    op.alter_column(
        "call_finalizations",
        "summary_command_id",
        new_column_name="current_command_id",
    )
    op.create_index(
        "ix_call_finalizations_current_command_id",
        "call_finalizations",
        ["current_command_id"],
    )
