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

T = TypeVar("T", bound="LocalVADCommit")


@_attrs_define
class LocalVADCommit:
    """
    Attributes:
        strategy (Literal['local_vad']):
    """

    strategy: Literal["local_vad"]

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
        strategy = cast(Literal["local_vad"], d.pop("strategy"))
        if strategy != "local_vad":
            raise ValueError(f"strategy must match const 'local_vad', got '{strategy}'")

        local_vad_commit = cls(
            strategy=strategy,
        )

        return local_vad_commit
