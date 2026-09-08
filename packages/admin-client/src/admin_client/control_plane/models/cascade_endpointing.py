from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="CascadeEndpointing")


@_attrs_define
class CascadeEndpointing:
    """
    Attributes:
        max_delay_seconds (float):
        min_delay_seconds (float):
    """

    max_delay_seconds: float
    min_delay_seconds: float

    def to_dict(self) -> dict[str, Any]:
        max_delay_seconds = self.max_delay_seconds

        min_delay_seconds = self.min_delay_seconds

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "max_delay_seconds": max_delay_seconds,
                "min_delay_seconds": min_delay_seconds,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        max_delay_seconds = d.pop("max_delay_seconds")

        min_delay_seconds = d.pop("min_delay_seconds")

        cascade_endpointing = cls(
            max_delay_seconds=max_delay_seconds,
            min_delay_seconds=min_delay_seconds,
        )

        return cascade_endpointing
