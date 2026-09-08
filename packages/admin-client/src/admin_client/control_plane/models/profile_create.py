from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="ProfileCreate")


@_attrs_define
class ProfileCreate:
    """
    Attributes:
        description (str):
        key (str):
        name (str):
    """

    description: str
    key: str
    name: str

    def to_dict(self) -> dict[str, Any]:
        description = self.description

        key = self.key

        name = self.name

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "description": description,
                "key": key,
                "name": name,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        description = d.pop("description")

        key = d.pop("key")

        name = d.pop("name")

        profile_create = cls(
            description=description,
            key=key,
            name=name,
        )

        return profile_create
