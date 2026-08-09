from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="UpdateInboundRouteRequest")


@_attrs_define
class UpdateInboundRouteRequest:
    """
    Attributes:
        enabled (bool | None | Unset):
        normalized_did (None | str | Unset):
    """

    enabled: bool | None | Unset = UNSET
    normalized_did: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        enabled: bool | None | Unset
        if isinstance(self.enabled, Unset):
            enabled = UNSET
        else:
            enabled = self.enabled

        normalized_did: None | str | Unset
        if isinstance(self.normalized_did, Unset):
            normalized_did = UNSET
        else:
            normalized_did = self.normalized_did

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if enabled is not UNSET:
            field_dict["enabled"] = enabled
        if normalized_did is not UNSET:
            field_dict["normalized_did"] = normalized_did

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)

        def _parse_enabled(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        enabled = _parse_enabled(d.pop("enabled", UNSET))

        def _parse_normalized_did(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        normalized_did = _parse_normalized_did(d.pop("normalized_did", UNSET))

        update_inbound_route_request = cls(
            enabled=enabled,
            normalized_did=normalized_did,
        )

        return update_inbound_route_request
