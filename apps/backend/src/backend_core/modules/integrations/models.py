from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend_core.platform.database import Base


class IntegrationProvider(StrEnum):
    GOOGLE_SHEETS = "google_sheets"
    MANAGED_WEBHOOK = "managed_webhook"


def provider_for_plan_type(plan_type: str) -> IntegrationProvider:
    return IntegrationProvider(plan_type.rsplit(".", 2)[0])


class IntegrationConnectionStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    INVALID = "invalid"


class IntegrationCredentialStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    REVOKED = "revoked"


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
    config: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
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


class IntegrationCredential(Base):
    __tablename__ = "integration_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "integration_id"],
            ["integration_connections.tenant_id", "integration_connections.id"],
            name="fk_integration_credentials_tenant_connection",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "integration_id", "version", name="uq_integration_credentials_version"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    integration_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[IntegrationCredentialStatus] = mapped_column(
        Enum(
            IntegrationCredentialStatus,
            name="integration_credential_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        default=IntegrationCredentialStatus.ACTIVE,
        server_default=IntegrationCredentialStatus.ACTIVE.value,
    )
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
