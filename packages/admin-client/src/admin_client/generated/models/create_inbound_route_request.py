from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="CreateInboundRouteRequest")


@_attrs_define
class CreateInboundRouteRequest:
    """
    Attributes:
        normalized_did (str):
        enabled (bool | Unset):  Default: True.
    """

    normalized_did: str
    enabled: bool | Unset = True

    def to_dict(self) -> dict[str, Any]:
        normalized_did = self.normalized_did

        enabled = self.enabled

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "normalized_did": normalized_did,
            }
        )
        if enabled is not UNSET:
            field_dict["enabled"] = enabled

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        normalized_did = d.pop("normalized_did")

        enabled = d.pop("enabled", UNSET)

        create_inbound_route_request = cls(
            normalized_did=normalized_did,
            enabled=enabled,
        )

        return create_inbound_route_request
