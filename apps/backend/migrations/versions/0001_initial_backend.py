"""Initial operational Backend schema."""

from alembic import op
import sqlalchemy as sa

from backend_core.platform.database.metadata import Base
from backend_core.platform.database.model_registry import load_models

revision = "0001_initial_backend"
down_revision = None
branch_labels = None
depends_on = None


def _tables():
    load_models()
    return tuple(Base.metadata.sorted_tables)


def upgrade() -> None:
    tables = _tables()
    for table in tables:
        constraints = sorted(
            table.constraints, key=lambda constraint: constraint.name or ""
        )
        op.create_table(table.name, *table.columns, *constraints)


def downgrade() -> None:
    tables = _tables()
    for table in reversed(tables):
        op.drop_table(table.name)
    enum_names = {
        column.type.name
        for table in tables
        for column in table.columns
        if isinstance(column.type, sa.Enum) and column.type.name
    }
    for name in sorted(enum_names):
        op.execute(sa.text(f'DROP TYPE IF EXISTS "{name}"'))
