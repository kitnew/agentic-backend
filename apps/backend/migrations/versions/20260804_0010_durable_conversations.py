"""Create durable call conversations and admin test-session idempotency."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260804_0010"
down_revision: str | None = "20260802_0009"
branch_labels: str | None = None
depends_on: str | None = None

conversation_status = postgresql.ENUM(
    "open",
    "complete",
    "incomplete",
    name="conversation_persistence_status",
)
message_role = postgresql.ENUM(
    "user",
    "assistant",
    name="conversation_message_role",
)


def upgrade() -> None:
    op.add_column(
        "call_sessions",
        sa.Column("admin_idempotency_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "call_sessions",
        sa.Column("admin_request_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_call_sessions_admin_idempotency_key",
        "call_sessions",
        ["admin_idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_call_sessions_tenant_id_id",
        "call_sessions",
        ["tenant_id", "id"],
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("call_session_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            conversation_status,
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "next_sequence_number",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "next_sequence_number > 0",
            name="ck_conversations_next_sequence_number_positive",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND closed_at IS NULL) OR "
            "(status IN ('complete', 'incomplete') AND closed_at IS NOT NULL)",
            name="ck_conversations_terminal_closed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_conversations_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "call_session_id"],
            ["call_sessions.tenant_id", "call_sessions.id"],
            name="fk_conversations_call_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id_id"),
        sa.UniqueConstraint(
            "call_session_id",
            name="uq_conversations_call_session_id",
        ),
    )

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "interrupted", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "persisted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence_number > 0",
            name="ck_conversation_messages_sequence_positive",
        ),
        sa.CheckConstraint(
            "btrim(content) <> ''",
            name="ck_conversation_messages_content_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name="fk_conversation_messages_conversation_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_messages"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_conversation_messages_tenant_id_id",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_conversation_messages_conversation_sequence",
        ),
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, tenant_id, status, created_at, ended_at FROM call_sessions")
    ).mappings()
    for row in rows:
        terminal = row["status"] in {"completed", "failed"}
        bind.execute(
            sa.text(
                "INSERT INTO conversations "
                "(id, tenant_id, call_session_id, status, next_sequence_number, "
                "created_at, closed_at, updated_at) "
                "VALUES (:id, :tenant_id, :call_session_id, :status, 1, "
                ":created_at, :closed_at, :updated_at)"
            ),
            {
                "id": uuid4(),
                "tenant_id": row["tenant_id"],
                "call_session_id": row["id"],
                "status": "incomplete" if terminal else "open",
                "created_at": row["created_at"],
                "closed_at": row["ended_at"] if terminal else None,
                "updated_at": row["ended_at"] or row["created_at"],
            },
        )


def downgrade() -> None:
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
    message_role.drop(op.get_bind(), checkfirst=True)
    conversation_status.drop(op.get_bind(), checkfirst=True)
    op.drop_constraint(
        "uq_call_sessions_tenant_id_id",
        "call_sessions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_call_sessions_admin_idempotency_key",
        "call_sessions",
        type_="unique",
    )
    op.drop_column("call_sessions", "admin_request_fingerprint")
    op.drop_column("call_sessions", "admin_idempotency_key")
