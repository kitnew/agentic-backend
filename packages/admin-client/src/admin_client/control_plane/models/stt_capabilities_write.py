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

T = TypeVar("T", bound="STTCapabilitiesWrite")


@_attrs_define
class STTCapabilitiesWrite:
    """
    Attributes:
        kind (Literal['stt']):
        supports_cascade (bool):
        supports_realtime_input_transcription (bool):
        supports_native_endpointing (bool | Unset):  Default: False.
    """

    kind: Literal["stt"]
    supports_cascade: bool
    supports_realtime_input_transcription: bool
    supports_native_endpointing: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        supports_cascade = self.supports_cascade

        supports_realtime_input_transcription = (
            self.supports_realtime_input_transcription
        )

        supports_native_endpointing = self.supports_native_endpointing

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "kind": kind,
                "supports_cascade": supports_cascade,
                "supports_realtime_input_transcription": supports_realtime_input_transcription,
            }
        )
        if supports_native_endpointing is not UNSET:
            field_dict["supports_native_endpointing"] = supports_native_endpointing

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        kind = cast(Literal["stt"], d.pop("kind"))
        if kind != "stt":
            raise ValueError(f"kind must match const 'stt', got '{kind}'")

        supports_cascade = d.pop("supports_cascade")

        supports_realtime_input_transcription = d.pop(
            "supports_realtime_input_transcription"
        )

        supports_native_endpointing = d.pop("supports_native_endpointing", UNSET)

        stt_capabilities_write = cls(
            kind=kind,
            supports_cascade=supports_cascade,
            supports_realtime_input_transcription=supports_realtime_input_transcription,
            supports_native_endpointing=supports_native_endpointing,
        )

        return stt_capabilities_write
