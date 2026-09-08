from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="PhoneNumberAssignmentCreate")


@_attrs_define
class PhoneNumberAssignmentCreate:
    """
    Attributes:
        phone_number (str):
    """

    phone_number: str

    def to_dict(self) -> dict[str, Any]:
        phone_number = self.phone_number

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "phone_number": phone_number,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        phone_number = d.pop("phone_number")

        phone_number_assignment_create = cls(
            phone_number=phone_number,
        )

        return phone_number_assignment_create
