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

from ..types import UNSET, Unset

T = TypeVar("T", bound="TTSRuntimeSettings")


@_attrs_define
class TTSRuntimeSettings:
    """
    Attributes:
        model (str):
        provider (Literal['elevenlabs']):
        voice_id (str):
        min_sentence_chars (int | Unset):  Default: 20.
    """

    model: str
    provider: Literal["elevenlabs"]
    voice_id: str
    min_sentence_chars: int | Unset = 20

    def to_dict(self) -> dict[str, Any]:
        model = self.model

        provider = self.provider

        voice_id = self.voice_id

        min_sentence_chars = self.min_sentence_chars

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "model": model,
                "provider": provider,
                "voice_id": voice_id,
            }
        )
        if min_sentence_chars is not UNSET:
            field_dict["min_sentence_chars"] = min_sentence_chars

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        model = d.pop("model")

        provider = cast(Literal["elevenlabs"], d.pop("provider"))
        if provider != "elevenlabs":
            raise ValueError(
                f"provider must match const 'elevenlabs', got '{provider}'"
            )

        voice_id = d.pop("voice_id")

        min_sentence_chars = d.pop("min_sentence_chars", UNSET)

        tts_runtime_settings = cls(
            model=model,
            provider=provider,
            voice_id=voice_id,
            min_sentence_chars=min_sentence_chars,
        )

        return tts_runtime_settings
