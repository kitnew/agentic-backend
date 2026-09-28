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

T = TypeVar("T", bound="STTCommit")


@_attrs_define
class STTCommit:
    """
    Attributes:
        strategy (Literal['stt']):
    """

    strategy: Literal["stt"]

    def to_dict(self) -> dict[str, Any]:
        strategy = self.strategy

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "strategy": strategy,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        strategy = cast(Literal["stt"], d.pop("strategy"))
        if strategy != "stt":
            raise ValueError(f"strategy must match const 'stt', got '{strategy}'")

        stt_commit = cls(
            strategy=strategy,
        )

        return stt_commit
