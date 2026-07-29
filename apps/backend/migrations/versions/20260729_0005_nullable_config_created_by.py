"""Allow config revisions without an authenticated admin identity.

Revision ID: 20260729_0005
Revises: 20260729_0004
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0005"
down_revision: str | None = "20260729_0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "tenant_config_revisions",
        "created_by",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE tenant_config_revisions "
        "SET created_by = '00000000-0000-0000-0000-000000000000' "
        "WHERE created_by IS NULL"
    )
    op.alter_column(
        "tenant_config_revisions",
        "created_by",
        existing_type=sa.Uuid(),
        nullable=False,
    )
