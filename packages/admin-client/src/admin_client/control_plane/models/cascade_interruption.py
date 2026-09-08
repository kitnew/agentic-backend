from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="CascadeInterruption")


@_attrs_define
class CascadeInterruption:
    """
    Attributes:
        enabled (bool):
        false_interruption_timeout_seconds (float):
        min_duration_seconds (float):
        min_words (int):
        resume_after_false_interruption (bool):
    """

    enabled: bool
    false_interruption_timeout_seconds: float
    min_duration_seconds: float
    min_words: int
    resume_after_false_interruption: bool

    def to_dict(self) -> dict[str, Any]:
        enabled = self.enabled

        false_interruption_timeout_seconds = self.false_interruption_timeout_seconds

        min_duration_seconds = self.min_duration_seconds

        min_words = self.min_words

        resume_after_false_interruption = self.resume_after_false_interruption

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "enabled": enabled,
                "false_interruption_timeout_seconds": false_interruption_timeout_seconds,
                "min_duration_seconds": min_duration_seconds,
                "min_words": min_words,
                "resume_after_false_interruption": resume_after_false_interruption,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        enabled = d.pop("enabled")

        false_interruption_timeout_seconds = d.pop("false_interruption_timeout_seconds")

        min_duration_seconds = d.pop("min_duration_seconds")

        min_words = d.pop("min_words")

        resume_after_false_interruption = d.pop("resume_after_false_interruption")

        cascade_interruption = cls(
            enabled=enabled,
            false_interruption_timeout_seconds=false_interruption_timeout_seconds,
            min_duration_seconds=min_duration_seconds,
            min_words=min_words,
            resume_after_false_interruption=resume_after_false_interruption,
        )

        return cascade_interruption
