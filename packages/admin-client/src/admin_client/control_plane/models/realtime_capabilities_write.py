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

T = TypeVar("T", bound="RealtimeCapabilitiesWrite")


@_attrs_define
class RealtimeCapabilitiesWrite:
    """
    Attributes:
        kind (Literal['realtime']):
        supports_semantic_vad (bool):
        supports_server_vad (bool):
    """

    kind: Literal["realtime"]
    supports_semantic_vad: bool
    supports_server_vad: bool

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        supports_semantic_vad = self.supports_semantic_vad

        supports_server_vad = self.supports_server_vad

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "kind": kind,
                "supports_semantic_vad": supports_semantic_vad,
                "supports_server_vad": supports_server_vad,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        kind = cast(Literal["realtime"], d.pop("kind"))
        if kind != "realtime":
            raise ValueError(f"kind must match const 'realtime', got '{kind}'")

        supports_semantic_vad = d.pop("supports_semantic_vad")

        supports_server_vad = d.pop("supports_server_vad")

        realtime_capabilities_write = cls(
            kind=kind,
            supports_semantic_vad=supports_semantic_vad,
            supports_server_vad=supports_server_vad,
        )

        return realtime_capabilities_write
