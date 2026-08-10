from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="LocalVADRuntimeSettings")


@_attrs_define
class LocalVADRuntimeSettings:
    """
    Attributes:
        activation_threshold (float):
        min_silence_seconds (float):
        min_speech_seconds (float):
    """

    activation_threshold: float
    min_silence_seconds: float
    min_speech_seconds: float

    def to_dict(self) -> dict[str, Any]:
        activation_threshold = self.activation_threshold

        min_silence_seconds = self.min_silence_seconds

        min_speech_seconds = self.min_speech_seconds

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "activation_threshold": activation_threshold,
                "min_silence_seconds": min_silence_seconds,
                "min_speech_seconds": min_speech_seconds,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        activation_threshold = d.pop("activation_threshold")

        min_silence_seconds = d.pop("min_silence_seconds")

        min_speech_seconds = d.pop("min_speech_seconds")

        local_vad_runtime_settings = cls(
            activation_threshold=activation_threshold,
            min_silence_seconds=min_silence_seconds,
            min_speech_seconds=min_speech_seconds,
        )

        return local_vad_runtime_settings
