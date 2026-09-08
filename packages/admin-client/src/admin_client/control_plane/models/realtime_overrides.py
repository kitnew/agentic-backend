from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="RealtimeOverrides")


@_attrs_define
class RealtimeOverrides:
    """
    Attributes:
        voice (str | Unset):
    """

    voice: str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        voice = self.voice

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if voice is not UNSET:
            field_dict["voice"] = voice

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        voice = d.pop("voice", UNSET)

        realtime_overrides = cls(
            voice=voice,
        )

        return realtime_overrides
