from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.realtime_overrides import RealtimeOverrides
    from ..models.stt_overrides import STTOverrides
    from ..models.tts_overrides import TTSOverrides


T = TypeVar("T", bound="RuntimeOverrides")


@_attrs_define
class RuntimeOverrides:
    """
    Attributes:
        realtime (RealtimeOverrides | Unset):
        stt (STTOverrides | Unset):
        tts (TTSOverrides | Unset):
    """

    realtime: RealtimeOverrides | Unset = UNSET
    stt: STTOverrides | Unset = UNSET
    tts: TTSOverrides | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        realtime: dict[str, Any] | Unset = UNSET
        if not isinstance(self.realtime, Unset):
            realtime = self.realtime.to_dict()

        stt: dict[str, Any] | Unset = UNSET
        if not isinstance(self.stt, Unset):
            stt = self.stt.to_dict()

        tts: dict[str, Any] | Unset = UNSET
        if not isinstance(self.tts, Unset):
            tts = self.tts.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if realtime is not UNSET:
            field_dict["realtime"] = realtime
        if stt is not UNSET:
            field_dict["stt"] = stt
        if tts is not UNSET:
            field_dict["tts"] = tts

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.realtime_overrides import RealtimeOverrides
        from ..models.stt_overrides import STTOverrides
        from ..models.tts_overrides import TTSOverrides

        d = dict(src_dict)
        _realtime = d.pop("realtime", UNSET)
        realtime: RealtimeOverrides | Unset
        if isinstance(_realtime, Unset):
            realtime = UNSET
        else:
            realtime = RealtimeOverrides.from_dict(_realtime)

        _stt = d.pop("stt", UNSET)
        stt: STTOverrides | Unset
        if isinstance(_stt, Unset):
            stt = UNSET
        else:
            stt = STTOverrides.from_dict(_stt)

        _tts = d.pop("tts", UNSET)
        tts: TTSOverrides | Unset
        if isinstance(_tts, Unset):
            tts = UNSET
        else:
            tts = TTSOverrides.from_dict(_tts)

        runtime_overrides = cls(
            realtime=realtime,
            stt=stt,
            tts=tts,
        )

        return runtime_overrides
