from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="IntegrationCredentialWrite")


@_attrs_define
class IntegrationCredentialWrite:
    """
    Attributes:
        api_key (str):
    """

    api_key: str

    def to_dict(self) -> dict[str, Any]:
        api_key = self.api_key

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "api_key": api_key,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        api_key = d.pop("api_key")

        integration_credential_write = cls(
            api_key=api_key,
        )

        return integration_credential_write
