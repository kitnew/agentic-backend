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

from ..models.realtime_semantic_vad_eagerness import RealtimeSemanticVADEagerness
from ..types import UNSET, Unset

T = TypeVar("T", bound="RealtimeSemanticVAD")


@_attrs_define
class RealtimeSemanticVAD:
    """
    Attributes:
        strategy (Literal['semantic_vad']):
        eagerness (RealtimeSemanticVADEagerness | Unset):  Default: RealtimeSemanticVADEagerness.AUTO.
    """

    strategy: Literal["semantic_vad"]
    eagerness: RealtimeSemanticVADEagerness | Unset = RealtimeSemanticVADEagerness.AUTO

    def to_dict(self) -> dict[str, Any]:
        strategy = self.strategy

        eagerness: str | Unset = UNSET
        if not isinstance(self.eagerness, Unset):
            eagerness = self.eagerness.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "strategy": strategy,
            }
        )
        if eagerness is not UNSET:
            field_dict["eagerness"] = eagerness

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        strategy = cast(Literal["semantic_vad"], d.pop("strategy"))
        if strategy != "semantic_vad":
            raise ValueError(
                f"strategy must match const 'semantic_vad', got '{strategy}'"
            )

        _eagerness = d.pop("eagerness", UNSET)
        eagerness: RealtimeSemanticVADEagerness | Unset
        if isinstance(_eagerness, Unset):
            eagerness = UNSET
        else:
            eagerness = RealtimeSemanticVADEagerness(_eagerness)

        realtime_semantic_vad = cls(
            strategy=strategy,
            eagerness=eagerness,
        )

        return realtime_semantic_vad
