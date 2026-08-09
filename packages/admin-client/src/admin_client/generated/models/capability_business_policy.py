from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="CapabilityBusinessPolicy")


@_attrs_define
class CapabilityBusinessPolicy:
    """
    Attributes:
        availability_proof_ttl_seconds (int | None | Unset):
        requires_availability_proof (bool | Unset):  Default: False.
        requires_caller_phone (bool | Unset):  Default: False.
        requires_final_confirmation (bool | Unset):  Default: False.
    """

    availability_proof_ttl_seconds: int | None | Unset = UNSET
    requires_availability_proof: bool | Unset = False
    requires_caller_phone: bool | Unset = False
    requires_final_confirmation: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        availability_proof_ttl_seconds: int | None | Unset
        if isinstance(self.availability_proof_ttl_seconds, Unset):
            availability_proof_ttl_seconds = UNSET
        else:
            availability_proof_ttl_seconds = self.availability_proof_ttl_seconds

        requires_availability_proof = self.requires_availability_proof

        requires_caller_phone = self.requires_caller_phone

        requires_final_confirmation = self.requires_final_confirmation

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if availability_proof_ttl_seconds is not UNSET:
            field_dict["availability_proof_ttl_seconds"] = (
                availability_proof_ttl_seconds
            )
        if requires_availability_proof is not UNSET:
            field_dict["requires_availability_proof"] = requires_availability_proof
        if requires_caller_phone is not UNSET:
            field_dict["requires_caller_phone"] = requires_caller_phone
        if requires_final_confirmation is not UNSET:
            field_dict["requires_final_confirmation"] = requires_final_confirmation

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)

        def _parse_availability_proof_ttl_seconds(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        availability_proof_ttl_seconds = _parse_availability_proof_ttl_seconds(
            d.pop("availability_proof_ttl_seconds", UNSET)
        )

        requires_availability_proof = d.pop("requires_availability_proof", UNSET)

        requires_caller_phone = d.pop("requires_caller_phone", UNSET)

        requires_final_confirmation = d.pop("requires_final_confirmation", UNSET)

        capability_business_policy = cls(
            availability_proof_ttl_seconds=availability_proof_ttl_seconds,
            requires_availability_proof=requires_availability_proof,
            requires_caller_phone=requires_caller_phone,
            requires_final_confirmation=requires_final_confirmation,
        )

        return capability_business_policy
