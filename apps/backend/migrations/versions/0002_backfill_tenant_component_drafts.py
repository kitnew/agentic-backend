"""backfill mandatory tenant authoring drafts for existing tenants."""

from alembic import op
from backend_core.modules.tenants.defaults import backfill_missing_component_drafts

revision = "0002_tenant_draft_backfill"
down_revision = "0001_component_release_baseline"
branch_labels = None
depends_on = None

def upgrade() -> None:
    backfill_missing_component_drafts(op.get_bind())


def downgrade() -> None:
    pass
