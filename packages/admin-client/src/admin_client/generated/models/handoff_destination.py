from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="HandoffDestination")


@_attrs_define
class HandoffDestination:
    """
    Attributes:
        description (str):
        phone_number (str):
    """

    description: str
    phone_number: str

    def to_dict(self) -> dict[str, Any]:
        description = self.description

        phone_number = self.phone_number

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "description": description,
                "phone_number": phone_number,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        description = d.pop("description")

        phone_number = d.pop("phone_number")

        handoff_destination = cls(
            description=description,
            phone_number=phone_number,
        )

        return handoff_destination
