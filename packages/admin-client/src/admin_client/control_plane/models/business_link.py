from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="BusinessLink")


@_attrs_define
class BusinessLink:
    """
    Attributes:
        label (str):
        value (str):
    """

    label: str
    value: str

    def to_dict(self) -> dict[str, Any]:
        label = self.label

        value = self.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "label": label,
                "value": value,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        label = d.pop("label")

        value = d.pop("value")

        business_link = cls(
            label=label,
            value=value,
        )

        return business_link
