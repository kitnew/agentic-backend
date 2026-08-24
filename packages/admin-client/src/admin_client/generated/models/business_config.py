from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="BusinessConfig")


@_attrs_define
class BusinessConfig:
    """
    Attributes:
        name (str):
        type_ (str):
    """

    name: str
    type_: str

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        type_ = self.type_

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "name": name,
                "type": type_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        name = d.pop("name")

        type_ = d.pop("type")

        business_config = cls(
            name=name,
            type_=type_,
        )

        return business_config
