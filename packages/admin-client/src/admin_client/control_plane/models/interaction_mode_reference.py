from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="InteractionModeReference")


@_attrs_define
class InteractionModeReference:
    """
    Attributes:
        mode_key (str):
    """

    mode_key: str

    def to_dict(self) -> dict[str, Any]:
        mode_key = self.mode_key

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "mode_key": mode_key,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        mode_key = d.pop("mode_key")

        interaction_mode_reference = cls(
            mode_key=mode_key,
        )

        return interaction_mode_reference
