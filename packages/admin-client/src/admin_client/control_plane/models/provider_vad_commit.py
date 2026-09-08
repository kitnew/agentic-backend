from __future__ import annotations

from collections.abc import Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.provider_vad import ProviderVAD


T = TypeVar("T", bound="ProviderVADCommit")


@_attrs_define
class ProviderVADCommit:
    """
    Attributes:
        provider_vad (ProviderVAD):
        strategy (Literal['provider_vad']):
    """

    provider_vad: ProviderVAD
    strategy: Literal["provider_vad"]

    def to_dict(self) -> dict[str, Any]:
        provider_vad = self.provider_vad.to_dict()

        strategy = self.strategy

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "provider_vad": provider_vad,
                "strategy": strategy,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.provider_vad import ProviderVAD

        d = dict(src_dict)
        provider_vad = ProviderVAD.from_dict(d.pop("provider_vad"))

        strategy = cast(Literal["provider_vad"], d.pop("strategy"))
        if strategy != "provider_vad":
            raise ValueError(
                f"strategy must match const 'provider_vad', got '{strategy}'"
            )

        provider_vad_commit = cls(
            provider_vad=provider_vad,
            strategy=strategy,
        )

        return provider_vad_commit
