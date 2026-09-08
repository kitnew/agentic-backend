from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.provider_connection_response_connection_config import (
        ProviderConnectionResponseConnectionConfig,
    )


T = TypeVar("T", bound="ProviderConnectionResponse")


@_attrs_define
class ProviderConnectionResponse:
    """
    Attributes:
        connection_config (ProviderConnectionResponseConnectionConfig):
        created_at (datetime.datetime):
        credential_ref (UUID):
        enabled (bool):
        id (UUID):
        key (str):
        provider_kind (str):
        updated_at (datetime.datetime):
    """

    connection_config: ProviderConnectionResponseConnectionConfig
    created_at: datetime.datetime
    credential_ref: UUID
    enabled: bool
    id: UUID
    key: str
    provider_kind: str
    updated_at: datetime.datetime

    def to_dict(self) -> dict[str, Any]:
        connection_config = self.connection_config.to_dict()

        created_at = self.created_at.isoformat()

        credential_ref = str(self.credential_ref)

        enabled = self.enabled

        id = str(self.id)

        key = self.key

        provider_kind = self.provider_kind

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "connection_config": connection_config,
                "created_at": created_at,
                "credential_ref": credential_ref,
                "enabled": enabled,
                "id": id,
                "key": key,
                "provider_kind": provider_kind,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.provider_connection_response_connection_config import (
            ProviderConnectionResponseConnectionConfig,
        )

        d = dict(src_dict)
        connection_config = ProviderConnectionResponseConnectionConfig.from_dict(
            d.pop("connection_config")
        )

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        credential_ref = UUID(d.pop("credential_ref"))

        enabled = d.pop("enabled")

        id = UUID(d.pop("id"))

        key = d.pop("key")

        provider_kind = d.pop("provider_kind")

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        provider_connection_response = cls(
            connection_config=connection_config,
            created_at=created_at,
            credential_ref=credential_ref,
            enabled=enabled,
            id=id,
            key=key,
            provider_kind=provider_kind,
            updated_at=updated_at,
        )

        return provider_connection_response
