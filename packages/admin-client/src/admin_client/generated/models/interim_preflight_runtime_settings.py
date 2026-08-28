from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="InterimPreflightRuntimeSettings")


@_attrs_define
class InterimPreflightRuntimeSettings:
    """
    Attributes:
        enabled (bool | Unset):  Default: False.
        max_generations_per_turn (int | Unset):  Default: 2.
        min_growth_chars (int | Unset):  Default: 12.
        min_transcript_chars (int | Unset):  Default: 20.
    """

    enabled: bool | Unset = False
    max_generations_per_turn: int | Unset = 2
    min_growth_chars: int | Unset = 12
    min_transcript_chars: int | Unset = 20

    def to_dict(self) -> dict[str, Any]:
        enabled = self.enabled

        max_generations_per_turn = self.max_generations_per_turn

        min_growth_chars = self.min_growth_chars

        min_transcript_chars = self.min_transcript_chars

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if enabled is not UNSET:
            field_dict["enabled"] = enabled
        if max_generations_per_turn is not UNSET:
            field_dict["max_generations_per_turn"] = max_generations_per_turn
        if min_growth_chars is not UNSET:
            field_dict["min_growth_chars"] = min_growth_chars
        if min_transcript_chars is not UNSET:
            field_dict["min_transcript_chars"] = min_transcript_chars

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        enabled = d.pop("enabled", UNSET)

        max_generations_per_turn = d.pop("max_generations_per_turn", UNSET)

        min_growth_chars = d.pop("min_growth_chars", UNSET)

        min_transcript_chars = d.pop("min_transcript_chars", UNSET)

        interim_preflight_runtime_settings = cls(
            enabled=enabled,
            max_generations_per_turn=max_generations_per_turn,
            min_growth_chars=min_growth_chars,
            min_transcript_chars=min_transcript_chars,
        )

        return interim_preflight_runtime_settings
