"""Allow new calls after PromptSet replaced legacy prompt bundles."""

import sqlalchemy as sa
from alembic import op

revision = "20260810_0018"
down_revision = "20260809_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "call_sessions",
        "prompt_bundle_revision_id",
        existing_type=sa.Uuid(),
        existing_nullable=False,
        nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM call_sessions "
            "WHERE prompt_bundle_revision_id IS NULL)"
        )
    ).scalar_one():
        raise RuntimeError(
            "cannot restore legacy prompt bundle requirement while new calls exist"
        )
    op.alter_column(
        "call_sessions",
        "prompt_bundle_revision_id",
        existing_type=sa.Uuid(),
        existing_nullable=True,
        nullable=False,
    )
