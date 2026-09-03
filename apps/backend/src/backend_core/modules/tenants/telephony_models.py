from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class TenantTelephonyProvisioning(Base):
    __tablename__ = "tenant_telephony_provisioning"
    __table_args__ = (
        ForeignKeyConstraint(("tenant_id",), ("tenants.id",), ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "phone_assignment_id", name="uq_tenant_telephony_provisioning_assignment"),
    )

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    phone_assignment_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    desired_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
