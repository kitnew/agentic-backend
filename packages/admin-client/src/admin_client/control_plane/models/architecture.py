from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="Architecture")


@_attrs_define
class Architecture:
    """
    Attributes:
        architecture_key (str):
    """

    architecture_key: str

    def to_dict(self) -> dict[str, Any]:
        architecture_key = self.architecture_key

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "architecture_key": architecture_key,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        architecture_key = d.pop("architecture_key")

        architecture = cls(
            architecture_key=architecture_key,
        )

        return architecture
