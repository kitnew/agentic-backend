from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.integration_provider import IntegrationProvider

T = TypeVar("T", bound="CreateIntegrationConnectionRequest")


@_attrs_define
class CreateIntegrationConnectionRequest:
    """
    Attributes:
        credential_ref (str):
        key (str):
        provider (IntegrationProvider):
    """

    credential_ref: str
    key: str
    provider: IntegrationProvider

    def to_dict(self) -> dict[str, Any]:
        credential_ref = self.credential_ref

        key = self.key

        provider = self.provider.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "credential_ref": credential_ref,
                "key": key,
                "provider": provider,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        credential_ref = d.pop("credential_ref")

        key = d.pop("key")

        provider = IntegrationProvider(d.pop("provider"))

        create_integration_connection_request = cls(
            credential_ref=credential_ref,
            key=key,
            provider=provider,
        )

        return create_integration_connection_request
