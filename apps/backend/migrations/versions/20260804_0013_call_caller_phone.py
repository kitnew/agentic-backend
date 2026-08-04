"""add trusted caller phone to call sessions

Revision ID: 20260804_0013
Revises: 20260804_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0013"
down_revision: str | None = "20260804_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "call_sessions",
        sa.Column("caller_phone_e164", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("call_sessions", "caller_phone_e164")
