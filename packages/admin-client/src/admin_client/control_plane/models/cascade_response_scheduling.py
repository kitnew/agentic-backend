from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="CascadeResponseScheduling")


@_attrs_define
class CascadeResponseScheduling:
    """
    Attributes:
        preemptive_generation (bool):
        preemptive_tts (bool):
    """

    preemptive_generation: bool
    preemptive_tts: bool

    def to_dict(self) -> dict[str, Any]:
        preemptive_generation = self.preemptive_generation

        preemptive_tts = self.preemptive_tts

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "preemptive_generation": preemptive_generation,
                "preemptive_tts": preemptive_tts,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        preemptive_generation = d.pop("preemptive_generation")

        preemptive_tts = d.pop("preemptive_tts")

        cascade_response_scheduling = cls(
            preemptive_generation=preemptive_generation,
            preemptive_tts=preemptive_tts,
        )

        return cascade_response_scheduling
