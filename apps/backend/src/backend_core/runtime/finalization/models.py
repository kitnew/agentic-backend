from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class FinalizationStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CallFinalization(Base):
    __tablename__ = "call_finalizations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    call_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("call_sessions.id", ondelete="CASCADE"), unique=True
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    status: Mapped[FinalizationStatus] = mapped_column(
        Enum(
            FinalizationStatus,
            name="call_finalization_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=FinalizationStatus.PENDING,
        server_default=FinalizationStatus.PENDING.value,
    )
    action_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    next_action_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    current_command_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
