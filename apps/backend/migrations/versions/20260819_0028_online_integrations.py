"""move tenant integrations to encrypted online credentials

Revision ID: 20260819_0028
Revises: 20260814_0027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260819_0028"
down_revision: str | None = "20260814_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

credential_status = postgresql.ENUM(
    "active",
    "retired",
    "revoked",
    name="integration_credential_status",
    create_type=False,
)


def upgrade() -> None:
    op.add_column(
        "integration_connections",
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "integration_connections",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute("UPDATE integration_connections SET status = 'disabled'")
    op.drop_column("integration_connections", "credential_ref")
    credential_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "integration_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", credential_status, nullable=False, server_default="active"),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["integration_connections.tenant_id", "integration_connections.id"],
            name="fk_integration_credentials_tenant_connection",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_integration_credentials"),
        sa.UniqueConstraint(
            "integration_id", "version", name="uq_integration_credentials_version"
        ),
    )
    op.create_index(
        "uq_integration_credentials_active",
        "integration_credentials",
        ["integration_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_integration_credentials_active", table_name="integration_credentials")
    op.drop_table("integration_credentials")
    credential_status.drop(op.get_bind(), checkfirst=True)
    op.add_column(
        "integration_connections",
        sa.Column(
            "credential_ref", sa.String(length=128), nullable=False, server_default="legacy"
        ),
    )
    op.drop_column("integration_connections", "revision")
    op.drop_column("integration_connections", "config")
