from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="TenantTelephonyConfig")


@_attrs_define
class TenantTelephonyConfig:
    """
    Attributes:
        phone_number (None | str | Unset):
    """

    phone_number: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        phone_number: None | str | Unset
        if isinstance(self.phone_number, Unset):
            phone_number = UNSET
        else:
            phone_number = self.phone_number

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if phone_number is not UNSET:
            field_dict["phone_number"] = phone_number

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)

        def _parse_phone_number(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        phone_number = _parse_phone_number(d.pop("phone_number", UNSET))

        tenant_telephony_config = cls(
            phone_number=phone_number,
        )

        return tenant_telephony_config
