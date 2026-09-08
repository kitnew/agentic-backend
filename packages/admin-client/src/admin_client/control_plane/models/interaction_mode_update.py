from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="InteractionModeUpdate")


@_attrs_define
class InteractionModeUpdate:
    """
    Attributes:
        description (str):
        name (str):
    """

    description: str
    name: str

    def to_dict(self) -> dict[str, Any]:
        description = self.description

        name = self.name

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "description": description,
                "name": name,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        description = d.pop("description")

        name = d.pop("name")

        interaction_mode_update = cls(
            description=description,
            name=name,
        )

        return interaction_mode_update
