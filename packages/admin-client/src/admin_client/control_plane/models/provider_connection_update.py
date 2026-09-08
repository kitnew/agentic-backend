from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.provider_connection_update_connection_config import (
        ProviderConnectionUpdateConnectionConfig,
    )


T = TypeVar("T", bound="ProviderConnectionUpdate")


@_attrs_define
class ProviderConnectionUpdate:
    """
    Attributes:
        connection_config (ProviderConnectionUpdateConnectionConfig):
        credential_ref (UUID):
    """

    connection_config: ProviderConnectionUpdateConnectionConfig
    credential_ref: UUID

    def to_dict(self) -> dict[str, Any]:
        connection_config = self.connection_config.to_dict()

        credential_ref = str(self.credential_ref)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "connection_config": connection_config,
                "credential_ref": credential_ref,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.provider_connection_update_connection_config import (
            ProviderConnectionUpdateConnectionConfig,
        )

        d = dict(src_dict)
        connection_config = ProviderConnectionUpdateConnectionConfig.from_dict(
            d.pop("connection_config")
        )

        credential_ref = UUID(d.pop("credential_ref"))

        provider_connection_update = cls(
            connection_config=connection_config,
            credential_ref=credential_ref,
        )

        return provider_connection_update
