"""make tenant telephony canonical

Revision ID: 20260822_0029
Revises: 20260819_0028
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0029"
down_revision: str | None = "20260819_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

status = postgresql.ENUM(
    "pending",
    "ready",
    "degraded",
    "error",
    name="telephony_provisioning_status",
    create_type=False,
)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM inbound_routes WHERE enabled
            GROUP BY tenant_id HAVING count(DISTINCT normalized_did) > 1
          ) THEN
            RAISE EXCEPTION 'tenant telephony migration found multiple enabled DIDs';
          END IF;
        END $$
        """
    )
    status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "tenant_telephony",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("config_revision_id", sa.Uuid(), nullable=False),
        sa.Column("phone_number", sa.String(16), nullable=True),
        sa.Column(
            "handoff_destinations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("provisioning_status", status, nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "phone_number IS NULL OR phone_number ~ '^\\+[1-9][0-9]{1,14}$'",
            name="ck_tenant_telephony_phone_number_e164",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["config_revision_id"], ["tenant_config_revisions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.UniqueConstraint("phone_number", name="uq_tenant_telephony_phone_number"),
    )
    op.execute(
        """
        UPDATE tenant_config_revisions r
        SET schema_version = 5,
            config = (r.config - 'handoff') || jsonb_build_object(
              'schema_version', 5,
              'telephony', jsonb_build_object(
                'phone_number', (
                  SELECT normalized_did FROM inbound_routes ir
                  WHERE ir.tenant_id = r.tenant_id AND ir.enabled LIMIT 1
                ),
                'handoff', coalesce(r.config->'handoff', '{"destinations": {}}'::jsonb)
              )
            )
        WHERE r.schema_version = 4
          AND (r.status = 'draft' OR EXISTS (
            SELECT 1 FROM tenants t WHERE t.active_config_revision_id = r.id
          ))
        """
    )
    # Only a published V5 revision is allowed to own the materialized row.
    # V1-V3 have no lossless Telephony upgrade (for example, V1 has no
    # profile/business fields), so their legacy routes are deliberately
    # retired without creating a runtime projection. They fail closed until
    # an operator publishes a valid V5 config.
    op.execute(
        """
        INSERT INTO tenant_telephony (
          tenant_id, config_revision_id, phone_number, handoff_destinations
        )
        SELECT t.id, r.id,
               r.config->'telephony'->>'phone_number',
               coalesce(r.config->'telephony'->'handoff'->'destinations', '{}'::jsonb)
        FROM tenants t
        JOIN tenant_config_revisions r ON r.id = t.active_config_revision_id
        WHERE r.schema_version = 5
          AND r.status = 'published'
        """
    )
    op.drop_table("inbound_routes")
    op.create_table(
        "platform_telephony",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inbound_trunk_id", sa.String(255), nullable=True),
        sa.Column("outbound_trunk_id", sa.String(255), nullable=True),
        sa.Column("dispatch_rule_id", sa.String(255), nullable=True),
        sa.Column("provisioning_status", status, nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_platform_telephony_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO platform_telephony (id) VALUES (1)")


def downgrade() -> None:
    op.create_table(
        "inbound_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_did", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "normalized_did ~ '^\\+[1-9][0-9]{1,14}$'",
            name="ck_inbound_routes_normalized_did_e164",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_inbound_routes_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "normalized_did", name="uq_inbound_routes_normalized_did"
        ),
    )
    op.create_index("ix_inbound_routes_tenant_id", "inbound_routes", ["tenant_id"])
    op.execute(
        """
        INSERT INTO inbound_routes (id, tenant_id, normalized_did)
        SELECT gen_random_uuid(), tenant_id, phone_number
        FROM tenant_telephony WHERE phone_number IS NOT NULL
        """
    )
    op.drop_table("platform_telephony")
    op.drop_table("tenant_telephony")
    status.drop(op.get_bind(), checkfirst=True)
