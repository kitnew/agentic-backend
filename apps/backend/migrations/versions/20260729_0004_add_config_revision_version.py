"""Add optimistic version to config revisions.

Revision ID: 20260729_0004
Revises: 20260728_0003
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0004"
down_revision: str | None = "20260728_0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_config_revisions",
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_tenant_config_revisions_version_positive",
        "tenant_config_revisions",
        "version > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tenant_config_revisions_version_positive",
        "tenant_config_revisions",
        type_="check",
    )
    op.drop_column("tenant_config_revisions", "version")
