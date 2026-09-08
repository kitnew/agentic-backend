from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="ProviderVAD")


@_attrs_define
class ProviderVAD:
    """
    Attributes:
        min_silence_ms (int):
        min_speech_ms (int):
        silence_threshold_seconds (float):
        threshold (float):
    """

    min_silence_ms: int
    min_speech_ms: int
    silence_threshold_seconds: float
    threshold: float

    def to_dict(self) -> dict[str, Any]:
        min_silence_ms = self.min_silence_ms

        min_speech_ms = self.min_speech_ms

        silence_threshold_seconds = self.silence_threshold_seconds

        threshold = self.threshold

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "min_silence_ms": min_silence_ms,
                "min_speech_ms": min_speech_ms,
                "silence_threshold_seconds": silence_threshold_seconds,
                "threshold": threshold,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        min_silence_ms = d.pop("min_silence_ms")

        min_speech_ms = d.pop("min_speech_ms")

        silence_threshold_seconds = d.pop("silence_threshold_seconds")

        threshold = d.pop("threshold")

        provider_vad = cls(
            min_silence_ms=min_silence_ms,
            min_speech_ms=min_speech_ms,
            silence_threshold_seconds=silence_threshold_seconds,
            threshold=threshold,
        )

        return provider_vad
