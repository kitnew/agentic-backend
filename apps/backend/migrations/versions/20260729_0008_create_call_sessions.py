"""Create durable call sessions.

Revision ID: 20260729_0008
Revises: 20260729_0007
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0008"
down_revision: str | None = "20260729_0007"
branch_labels: str | None = None
depends_on: str | None = None

call_channel = postgresql.ENUM("sip", name="call_channel")
call_direction = postgresql.ENUM("inbound", name="call_direction")
call_session_status = postgresql.ENUM(
    "created",
    "active",
    "completed",
    "failed",
    name="call_session_status",
)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_prompt_bundle_revisions_tenant_id_id",
        "prompt_bundle_revisions",
        ["tenant_id", "id"],
    )
    op.create_table(
        "call_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_config_revision_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_bundle_revision_id", sa.Uuid(), nullable=False),
        sa.Column("channel", call_channel, nullable=False),
        sa.Column("direction", call_direction, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_call_id", sa.String(length=255), nullable=False),
        sa.Column("room_name", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            call_session_status,
            server_default="created",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
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
            name="ck_call_sessions_lifecycle_fields",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_call_sessions_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tenant_config_revision_id"],
            [
                "tenant_config_revisions.tenant_id",
                "tenant_config_revisions.id",
            ],
            name="fk_call_sessions_config_revision_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "prompt_bundle_revision_id"],
            [
                "prompt_bundle_revisions.tenant_id",
                "prompt_bundle_revisions.id",
            ],
            name="fk_call_sessions_prompt_revision_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_call_sessions"),
        sa.UniqueConstraint(
            "provider",
            "provider_call_id",
            name="uq_call_sessions_provider_call_id",
        ),
    )
    op.create_index(
        "ix_call_sessions_tenant_created_at",
        "call_sessions",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_call_sessions_tenant_created_at",
        table_name="call_sessions",
    )
    op.drop_table("call_sessions")
    call_session_status.drop(op.get_bind(), checkfirst=True)
    call_direction.drop(op.get_bind(), checkfirst=True)
    call_channel.drop(op.get_bind(), checkfirst=True)
    op.drop_constraint(
        "uq_prompt_bundle_revisions_tenant_id_id",
        "prompt_bundle_revisions",
        type_="unique",
    )
