"""Add inbound SIP transport correlation to CallSession."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0023"
down_revision: str | None = "20260811_0022"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    for name, length in (
        ("called_phone_e164", 32),
        ("caller_phone_raw", 64),
        ("called_phone_raw", 64),
        ("sip_call_id", 255),
        ("sip_call_id_full", 255),
        ("sip_trunk_id", 255),
        ("sip_dispatch_rule_id", 255),
        ("livekit_participant_identity", 255),
    ):
        op.add_column(
            "call_sessions", sa.Column(name, sa.String(length=length), nullable=True)
        )
    op.create_index(
        "uq_call_sessions_provider_sip_call_id",
        "call_sessions",
        ["provider", "sip_call_id"],
        unique=True,
        postgresql_where=sa.text("sip_call_id IS NOT NULL"),
    )
    op.create_index(
        "uq_call_sessions_provider_sip_call_id_full",
        "call_sessions",
        ["provider", "sip_call_id_full"],
        unique=True,
        postgresql_where=sa.text("sip_call_id_full IS NOT NULL"),
    )


def downgrade() -> None:
    # This intentionally discards SIP diagnostics; the CallSession rows remain.
    op.drop_index(
        "uq_call_sessions_provider_sip_call_id_full", table_name="call_sessions"
    )
    op.drop_index(
        "uq_call_sessions_provider_sip_call_id", table_name="call_sessions"
    )
    for name in (
        "livekit_participant_identity",
        "sip_dispatch_rule_id",
        "sip_trunk_id",
        "sip_call_id_full",
        "sip_call_id",
        "called_phone_raw",
        "caller_phone_raw",
        "called_phone_e164",
    ):
        op.drop_column("call_sessions", name)
