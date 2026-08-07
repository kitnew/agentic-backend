from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class CallChannel(StrEnum):
    SIP = "sip"
    WEB = "web"


class CallDirection(StrEnum):
    INBOUND = "inbound"


class CallSessionStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class CallSession(Base):
    __tablename__ = "call_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "tenant_config_revision_id"),
            (
                "tenant_config_revisions.tenant_id",
                "tenant_config_revisions.id",
            ),
            name="fk_call_sessions_config_revision_same_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "prompt_set_revision_id"),
            ("prompt_set_revisions.tenant_id", "prompt_set_revisions.id"),
            name="fk_call_sessions_prompt_set_revision_same_tenant",
        ),
        UniqueConstraint(
            "provider",
            "provider_call_id",
            name="uq_call_sessions_provider_call_id",
        ),
        UniqueConstraint(
            "provider",
            "provider_dispatch_id",
            name="uq_call_sessions_provider_dispatch_id",
        ),
        UniqueConstraint(
            "admin_idempotency_key",
            name="uq_call_sessions_admin_idempotency_key",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_call_sessions_tenant_id_id",
        ),
        CheckConstraint(
            """
            (status = 'created' AND started_at IS NULL AND ended_at IS NULL
                AND failure_reason IS NULL)
            OR (status = 'active' AND started_at IS NOT NULL AND ended_at IS NULL
                AND failure_reason IS NULL)
            OR (status = 'completed' AND started_at IS NOT NULL
                AND ended_at IS NOT NULL AND failure_reason IS NULL)
            OR (status = 'failed' AND ended_at IS NOT NULL
                AND failure_reason IS NOT NULL)
            """,
            name="ck_call_sessions_lifecycle_fields",
        ),
        Index("ix_call_sessions_tenant_created_at", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "tenants.id",
            name="fk_call_sessions_tenant_id_tenants",
        ),
    )
    tenant_config_revision_id: Mapped[UUID] = mapped_column(Uuid)
    prompt_set_revision_id: Mapped[UUID] = mapped_column(Uuid)
    channel: Mapped[CallChannel] = mapped_column(
        Enum(
            CallChannel,
            name="call_channel",
            values_callable=lambda values: [value.value for value in values],
        )
    )
    direction: Mapped[CallDirection] = mapped_column(
        Enum(
            CallDirection,
            name="call_direction",
            values_callable=lambda values: [value.value for value in values],
        )
    )
    provider: Mapped[str] = mapped_column(String(64))
    provider_call_id: Mapped[str] = mapped_column(String(255))
    caller_phone_e164: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_dispatch_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    admin_idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    admin_request_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    room_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[CallSessionStatus] = mapped_column(
        Enum(
            CallSessionStatus,
            name="call_session_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=CallSessionStatus.CREATED,
        server_default=CallSessionStatus.CREATED.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
