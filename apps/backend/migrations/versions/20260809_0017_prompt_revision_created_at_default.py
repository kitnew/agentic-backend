"""Add server timestamps to prompt revision inserts."""

import sqlalchemy as sa
from alembic import op

revision = "20260809_0017"
down_revision = "20260807_0016"
branch_labels = None
depends_on = None

_TABLES = (
    "system_prompt_revisions",
    "profile_prompt_revisions",
    "tenant_prompt_revisions",
    "knowledge_base_revisions",
    "prompt_set_revisions",
)


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
            server_default=sa.text("now()"),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
            server_default=None,
        )
