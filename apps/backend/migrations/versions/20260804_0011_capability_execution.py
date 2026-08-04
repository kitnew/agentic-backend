"""Add tenant integration connections and durable capability execution."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260804_0011"
down_revision: str | None = "20260804_0010"
branch_labels: str | None = None
depends_on: str | None = None

integration_provider = postgresql.ENUM("google_sheets", name="integration_provider")
integration_status = postgresql.ENUM(
    "active", "disabled", "invalid", name="integration_connection_status"
)
invocation_status = postgresql.ENUM(
    "pending",
    "queued",
    "running",
    "succeeded",
    "failed",
    "expired",
    name="capability_invocation_status",
)


def upgrade() -> None:
    op.create_table(
        "integration_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("provider", integration_provider, nullable=False),
        sa.Column("credential_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "status", integration_status, server_default="active", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_integration_connections_tenant_id_tenants",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_integration_connections"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_integration_connections_tenant_id_id"
        ),
        sa.UniqueConstraint(
            "tenant_id", "key", name="uq_integration_connections_tenant_key"
        ),
    )
    op.create_table(
        "capability_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=255), nullable=False),
        sa.Column("semantic_key", sa.String(length=128), nullable=False),
        sa.Column("semantic_version", sa.Integer(), nullable=False),
        sa.Column("tenant_config_revision_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", invocation_status, server_default="pending", nullable=False
        ),
        sa.Column(
            "canonical_input", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "execution_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "technical_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "semantic_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "call_id"],
            ["call_sessions.tenant_id", "call_sessions.id"],
            name="fk_capability_invocations_call_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name="fk_capability_invocations_conversation_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tenant_config_revision_id"],
            ["tenant_config_revisions.tenant_id", "tenant_config_revisions.id"],
            name="fk_capability_invocations_config_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_capability_invocations"),
        sa.UniqueConstraint(
            "operation_id", name="uq_capability_invocations_operation_id"
        ),
        sa.UniqueConstraint("job_id", name="uq_capability_invocations_job_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "call_id",
            "tool_call_id",
            name="uq_capability_invocations_tenant_call_tool_call",
        ),
    )
    op.create_index(
        "ix_capability_invocations_tenant_created_at",
        "capability_invocations",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("capability_invocation_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempts >= 0", name="ck_outbox_messages_attempts_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["capability_invocation_id"],
            ["capability_invocations.id"],
            name="fk_outbox_messages_capability_invocation_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_messages"),
        sa.UniqueConstraint("job_id", name="uq_outbox_messages_job_id"),
    )
    op.create_index(
        "ix_outbox_messages_undispatched",
        "outbox_messages",
        ["created_at"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_messages_undispatched", table_name="outbox_messages")
    op.drop_table("outbox_messages")
    op.drop_index(
        "ix_capability_invocations_tenant_created_at",
        table_name="capability_invocations",
    )
    op.drop_table("capability_invocations")
    op.drop_table("integration_connections")
    invocation_status.drop(op.get_bind(), checkfirst=True)
    integration_status.drop(op.get_bind(), checkfirst=True)
    integration_provider.drop(op.get_bind(), checkfirst=True)
