from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="ServerVADRuntimeSettings")


@_attrs_define
class ServerVADRuntimeSettings:
    """
    Attributes:
        activity_threshold (float):
        min_silence_ms (int):
        min_speech_ms (int):
        silence_threshold_seconds (float):
    """

    activity_threshold: float
    min_silence_ms: int
    min_speech_ms: int
    silence_threshold_seconds: float

    def to_dict(self) -> dict[str, Any]:
        activity_threshold = self.activity_threshold

        min_silence_ms = self.min_silence_ms

        min_speech_ms = self.min_speech_ms

        silence_threshold_seconds = self.silence_threshold_seconds

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "activity_threshold": activity_threshold,
                "min_silence_ms": min_silence_ms,
                "min_speech_ms": min_speech_ms,
                "silence_threshold_seconds": silence_threshold_seconds,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        activity_threshold = d.pop("activity_threshold")

        min_silence_ms = d.pop("min_silence_ms")

        min_speech_ms = d.pop("min_speech_ms")

        silence_threshold_seconds = d.pop("silence_threshold_seconds")

        server_vad_runtime_settings = cls(
            activity_threshold=activity_threshold,
            min_silence_ms=min_silence_ms,
            min_speech_ms=min_speech_ms,
            silence_threshold_seconds=silence_threshold_seconds,
        )

        return server_vad_runtime_settings
