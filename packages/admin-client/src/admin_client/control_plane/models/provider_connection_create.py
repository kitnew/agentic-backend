from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.provider_connection_create_connection_config import (
        ProviderConnectionCreateConnectionConfig,
    )


T = TypeVar("T", bound="ProviderConnectionCreate")


@_attrs_define
class ProviderConnectionCreate:
    """
    Attributes:
        connection_config (ProviderConnectionCreateConnectionConfig):
        credential_ref (UUID):
        key (str):
        provider_kind (str):
    """

    connection_config: ProviderConnectionCreateConnectionConfig
    credential_ref: UUID
    key: str
    provider_kind: str

    def to_dict(self) -> dict[str, Any]:
        connection_config = self.connection_config.to_dict()

        credential_ref = str(self.credential_ref)

        key = self.key

        provider_kind = self.provider_kind

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "connection_config": connection_config,
                "credential_ref": credential_ref,
                "key": key,
                "provider_kind": provider_kind,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.provider_connection_create_connection_config import (
            ProviderConnectionCreateConnectionConfig,
        )

        d = dict(src_dict)
        connection_config = ProviderConnectionCreateConnectionConfig.from_dict(
            d.pop("connection_config")
        )

        credential_ref = UUID(d.pop("credential_ref"))

        key = d.pop("key")

        provider_kind = d.pop("provider_kind")

        provider_connection_create = cls(
            connection_config=connection_config,
            credential_ref=credential_ref,
            key=key,
            provider_kind=provider_kind,
        )

        return provider_connection_create
