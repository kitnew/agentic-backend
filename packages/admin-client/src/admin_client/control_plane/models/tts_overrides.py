from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="TTSOverrides")


@_attrs_define
class TTSOverrides:
    """
    Attributes:
        voice_id (str | Unset):
    """

    voice_id: str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        voice_id = self.voice_id

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if voice_id is not UNSET:
            field_dict["voice_id"] = voice_id

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        voice_id = d.pop("voice_id", UNSET)

        tts_overrides = cls(
            voice_id=voice_id,
        )

        return tts_overrides
