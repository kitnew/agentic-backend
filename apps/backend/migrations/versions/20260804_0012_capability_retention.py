"""Add capability PII purge marker."""

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0012"
down_revision: str | None = "20260804_0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "capability_invocations",
        sa.Column("pii_purged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("capability_invocations", "pii_purged_at")
