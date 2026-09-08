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

T = TypeVar("T", bound="TTSCapabilitiesWrite")


@_attrs_define
class TTSCapabilitiesWrite:
    """
    Attributes:
        kind (Literal['tts']):
    """

    kind: Literal["tts"]

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "kind": kind,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        kind = cast(Literal["tts"], d.pop("kind"))
        if kind != "tts":
            raise ValueError(f"kind must match const 'tts', got '{kind}'")

        tts_capabilities_write = cls(
            kind=kind,
        )

        return tts_capabilities_write
