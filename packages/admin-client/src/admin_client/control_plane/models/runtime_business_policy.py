from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="RuntimeBusinessPolicy")


@_attrs_define
class RuntimeBusinessPolicy:
    """
    Attributes:
        requires_caller_phone (bool | Unset):  Default: False.
        requires_final_confirmation (bool | Unset):  Default: False.
    """

    requires_caller_phone: bool | Unset = False
    requires_final_confirmation: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        requires_caller_phone = self.requires_caller_phone

        requires_final_confirmation = self.requires_final_confirmation

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if requires_caller_phone is not UNSET:
            field_dict["requires_caller_phone"] = requires_caller_phone
        if requires_final_confirmation is not UNSET:
            field_dict["requires_final_confirmation"] = requires_final_confirmation

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        requires_caller_phone = d.pop("requires_caller_phone", UNSET)

        requires_final_confirmation = d.pop("requires_final_confirmation", UNSET)

        runtime_business_policy = cls(
            requires_caller_phone=requires_caller_phone,
            requires_final_confirmation=requires_final_confirmation,
        )

        return runtime_business_policy
