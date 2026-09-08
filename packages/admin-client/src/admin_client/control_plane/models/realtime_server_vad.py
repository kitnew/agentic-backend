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

T = TypeVar("T", bound="RealtimeServerVAD")


@_attrs_define
class RealtimeServerVAD:
    """
    Attributes:
        strategy (Literal['server_vad']):
        activation_threshold (float | Unset):  Default: 0.5.
        silence_duration_ms (int | Unset):  Default: 200.
    """

    strategy: Literal["server_vad"]
    activation_threshold: float | Unset = 0.5
    silence_duration_ms: int | Unset = 200

    def to_dict(self) -> dict[str, Any]:
        strategy = self.strategy

        activation_threshold = self.activation_threshold

        silence_duration_ms = self.silence_duration_ms

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "strategy": strategy,
            }
        )
        if activation_threshold is not UNSET:
            field_dict["activation_threshold"] = activation_threshold
        if silence_duration_ms is not UNSET:
            field_dict["silence_duration_ms"] = silence_duration_ms

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        strategy = cast(Literal["server_vad"], d.pop("strategy"))
        if strategy != "server_vad":
            raise ValueError(
                f"strategy must match const 'server_vad', got '{strategy}'"
            )

        activation_threshold = d.pop("activation_threshold", UNSET)

        silence_duration_ms = d.pop("silence_duration_ms", UNSET)

        realtime_server_vad = cls(
            strategy=strategy,
            activation_threshold=activation_threshold,
            silence_duration_ms=silence_duration_ms,
        )

        return realtime_server_vad
