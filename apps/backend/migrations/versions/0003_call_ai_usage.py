"""Store cumulative per-call AI provider usage without changing call lifecycle."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_call_ai_usage"
down_revision = "0002_handoff_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "call_ai_usage",
        sa.Column("call_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider", sa.String(128), primary_key=True),
        sa.Column("service", sa.String(16), primary_key=True),
        sa.Column("model", sa.String(255), primary_key=True),
        sa.Column("source", sa.String(64), primary_key=True),
        sa.Column("counters", JSONB(), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(20, 9)),
        sa.Column("estimated_cost_source", sa.String(255)),
        sa.Column("provider_cost_usd", sa.Numeric(20, 9)),
        sa.Column("reconciled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ("tenant_id", "call_id"),
            ("call_sessions.tenant_id", "call_sessions.id"),
            name="fk_call_ai_usage_tenant_call",
        ),
    )
    op.create_index(
        "ix_call_ai_usage_tenant_observed",
        "call_ai_usage",
        ("tenant_id", "last_observed_at"),
    )


def downgrade() -> None:
    op.drop_index("ix_call_ai_usage_tenant_observed", table_name="call_ai_usage")
    op.drop_table("call_ai_usage")
