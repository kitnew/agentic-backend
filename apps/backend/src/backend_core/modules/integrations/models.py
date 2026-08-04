from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class IntegrationProvider(StrEnum):
    GOOGLE_SHEETS = "google_sheets"


class IntegrationConnectionStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    INVALID = "invalid"


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "key", name="uq_integration_connections_tenant_key"
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_integration_connections_tenant_id_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", name="fk_integration_connections_tenant_id_tenants"),
    )
    key: Mapped[str] = mapped_column(String(64))
    provider: Mapped[IntegrationProvider] = mapped_column(
        Enum(
            IntegrationProvider,
            name="integration_provider",
            values_callable=lambda values: [value.value for value in values],
        )
    )
    credential_ref: Mapped[str] = mapped_column(String(128))
    status: Mapped[IntegrationConnectionStatus] = mapped_column(
        Enum(
            IntegrationConnectionStatus,
            name="integration_connection_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=IntegrationConnectionStatus.ACTIVE,
        server_default=IntegrationConnectionStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
