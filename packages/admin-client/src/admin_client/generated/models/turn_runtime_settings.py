from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="TurnRuntimeSettings")


@_attrs_define
class TurnRuntimeSettings:
    """
    Attributes:
        detection (Literal['stt']):
        max_endpointing_delay_seconds (float):
        min_endpointing_delay_seconds (float):
    """

    detection: Literal["stt"]
    max_endpointing_delay_seconds: float
    min_endpointing_delay_seconds: float

    def to_dict(self) -> dict[str, Any]:
        detection = self.detection

        max_endpointing_delay_seconds = self.max_endpointing_delay_seconds

        min_endpointing_delay_seconds = self.min_endpointing_delay_seconds

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "detection": detection,
                "max_endpointing_delay_seconds": max_endpointing_delay_seconds,
                "min_endpointing_delay_seconds": min_endpointing_delay_seconds,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        detection = cast(Literal["stt"], d.pop("detection"))
        if detection != "stt":
            raise ValueError(f"detection must match const 'stt', got '{detection}'")

        max_endpointing_delay_seconds = d.pop("max_endpointing_delay_seconds")

        min_endpointing_delay_seconds = d.pop("min_endpointing_delay_seconds")

        turn_runtime_settings = cls(
            detection=detection,
            max_endpointing_delay_seconds=max_endpointing_delay_seconds,
            min_endpointing_delay_seconds=min_endpointing_delay_seconds,
        )

        return turn_runtime_settings
