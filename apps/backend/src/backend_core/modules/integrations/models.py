from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
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


class IntegrationKind(StrEnum):
    GOOGLE_SHEETS = "google_sheets"
    HTTP = "http"


IntegrationProvider = IntegrationKind


class IntegrationConnectionStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    INVALID = "invalid"


def provider_for_plan_type(plan_type: str) -> IntegrationProvider:
    return IntegrationKind(plan_type.rsplit(".", 2)[0])


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
    kind: Mapped[IntegrationKind] = mapped_column(
        Enum(
            IntegrationKind,
            name="integration_kind",
            values_callable=lambda values: [value.value for value in values],
        )
    )
    configuration: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __init__(self, **kwargs: object) -> None:
        # Internal model aliases keep the untouched Google Sheets fixtures readable.
        if "provider" in kwargs:
            kwargs["kind"] = kwargs.pop("provider")
        if "config" in kwargs:
            kwargs["configuration"] = kwargs.pop("config")
        if "status" in kwargs:
            kwargs["enabled"] = kwargs.pop("status") is IntegrationConnectionStatus.ACTIVE
        super().__init__(**kwargs)

    @property
    def provider(self) -> IntegrationKind:
        return self.kind

    @property
    def config(self) -> dict[str, object]:
        return self.configuration

    @property
    def status(self) -> IntegrationConnectionStatus:
        return IntegrationConnectionStatus.ACTIVE if self.enabled else IntegrationConnectionStatus.DISABLED

    @status.setter
    def status(self, value: IntegrationConnectionStatus) -> None:
        self.enabled = value is IntegrationConnectionStatus.ACTIVE


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
