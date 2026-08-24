"""first production schema: component releases and bundle-only runtime."""

from alembic import op
from backend_core.platform.database.metadata import Base

revision = "0001_component_release_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind(), checkfirst=True)
