from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.handoff_config import HandoffConfig


T = TypeVar("T", bound="TenantTelephonyConfig")


@_attrs_define
class TenantTelephonyConfig:
    """
    Attributes:
        handoff (HandoffConfig | Unset):
        phone_number (None | str | Unset):
    """

    handoff: HandoffConfig | Unset = UNSET
    phone_number: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        handoff: dict[str, Any] | Unset = UNSET
        if not isinstance(self.handoff, Unset):
            handoff = self.handoff.to_dict()

        phone_number: None | str | Unset
        if isinstance(self.phone_number, Unset):
            phone_number = UNSET
        else:
            phone_number = self.phone_number

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if handoff is not UNSET:
            field_dict["handoff"] = handoff
        if phone_number is not UNSET:
            field_dict["phone_number"] = phone_number

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.handoff_config import HandoffConfig

        d = dict(src_dict)
        _handoff = d.pop("handoff", UNSET)
        handoff: HandoffConfig | Unset
        if isinstance(_handoff, Unset):
            handoff = UNSET
        else:
            handoff = HandoffConfig.from_dict(_handoff)

        def _parse_phone_number(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        phone_number = _parse_phone_number(d.pop("phone_number", UNSET))

        tenant_telephony_config = cls(
            handoff=handoff,
            phone_number=phone_number,
        )

        return tenant_telephony_config
