"""Authoritative cumulative AI usage for a call."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class CallAIUsage(Base):
    __tablename__ = "call_ai_usage"
    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "call_id"),
            ("call_sessions.tenant_id", "call_sessions.id"),
            name="fk_call_ai_usage_tenant_call",
        ),
        Index("ix_call_ai_usage_tenant_observed", "tenant_id", "last_observed_at"),
    )

    call_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    provider: Mapped[str] = mapped_column(String(128), primary_key=True)
    service: Mapped[str] = mapped_column(String(16), primary_key=True)
    model: Mapped[str] = mapped_column(String(255), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    counters: Mapped[dict[str, int | float]] = mapped_column(JSONB)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 9), nullable=True
    )
    estimated_cost_source: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    provider_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 9), nullable=True
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
