from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="HttpConnectionSecurity")


@_attrs_define
class HttpConnectionSecurity:
    """
    Attributes:
        additional_allowed_hosts (list[str] | Unset):
    """

    additional_allowed_hosts: list[str] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        additional_allowed_hosts: list[str] | Unset = UNSET
        if not isinstance(self.additional_allowed_hosts, Unset):
            additional_allowed_hosts = self.additional_allowed_hosts

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if additional_allowed_hosts is not UNSET:
            field_dict["additional_allowed_hosts"] = additional_allowed_hosts

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        additional_allowed_hosts = cast(
            list[str], d.pop("additional_allowed_hosts", UNSET)
        )

        http_connection_security = cls(
            additional_allowed_hosts=additional_allowed_hosts,
        )

        return http_connection_security
