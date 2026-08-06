"""add managed webhook integration provider

Revision ID: 20260806_0015
Revises: 20260804_0014
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260806_0015"
down_revision: str | None = "20260804_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE integration_provider ADD VALUE IF NOT EXISTS 'managed_webhook'")


def downgrade() -> None:
    # PostgreSQL does not safely remove enum values; keep the additive value.
    pass
