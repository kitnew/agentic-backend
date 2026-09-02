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
from sqlalchemy import (
    text as sql_text,
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
    STARTED = "started"
    CONNECTED = "connected"
    ENDED = "ended"
    FAILED = "failed"


class CallSession(Base):
    __tablename__ = "call_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "tenant_release_id", "runtime_bundle_id"),
            ("tenant_releases.tenant_id", "tenant_releases.id", "tenant_releases.runtime_bundle_id"),
            name="fk_call_sessions_release_bundle_same_tenant",
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
            OR (status = 'started' AND started_at IS NOT NULL
                AND connected_at IS NULL AND ended_at IS NULL
                AND failure_reason IS NULL)
            OR (status = 'connected' AND started_at IS NOT NULL
                AND connected_at IS NOT NULL AND ended_at IS NULL
                AND failure_reason IS NULL)
            OR (status = 'ended' AND started_at IS NOT NULL
                AND connected_at IS NOT NULL
                AND ended_at IS NOT NULL AND failure_reason IS NULL)
            OR (status = 'failed' AND ended_at IS NOT NULL
                AND failure_reason IS NOT NULL)
            """,
            name="ck_call_sessions_lifecycle_fields",
        ),
        Index("ix_call_sessions_tenant_created_at", "tenant_id", "created_at"),
        Index(
            "uq_call_sessions_provider_sip_call_id",
            "provider",
            "sip_call_id",
            unique=True,
            postgresql_where=sql_text("sip_call_id IS NOT NULL"),
        ),
        Index(
            "uq_call_sessions_provider_sip_call_id_full",
            "provider",
            "sip_call_id_full",
            unique=True,
            postgresql_where=sql_text("sip_call_id_full IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "tenants.id",
            name="fk_call_sessions_tenant_id_tenants",
        ),
    )
    tenant_release_id: Mapped[UUID] = mapped_column(Uuid)
    runtime_bundle_id: Mapped[UUID] = mapped_column(Uuid)
    execution_snapshot_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
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
    called_phone_e164: Mapped[str | None] = mapped_column(String(32), nullable=True)
    caller_phone_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    called_phone_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sip_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sip_call_id_full: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sip_trunk_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sip_dispatch_rule_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    livekit_participant_identity: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
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
    handoff_tool_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    handoff_destination: Mapped[str | None] = mapped_column(String(64), nullable=True)
    handoff_participant_identity: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    handoff_sip_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
