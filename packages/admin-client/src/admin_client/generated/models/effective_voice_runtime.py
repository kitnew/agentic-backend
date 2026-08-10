from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.llm_runtime_settings import LLMRuntimeSettings
    from ..models.local_vad_runtime_settings import LocalVADRuntimeSettings
    from ..models.stt_runtime_settings import STTRuntimeSettings
    from ..models.tts_runtime_settings import TTSRuntimeSettings
    from ..models.turn_runtime_settings import TurnRuntimeSettings


T = TypeVar("T", bound="EffectiveVoiceRuntime")


@_attrs_define
class EffectiveVoiceRuntime:
    """
    Attributes:
        llm (LLMRuntimeSettings):
        local_vad (LocalVADRuntimeSettings):
        locale (str):
        stt (STTRuntimeSettings):
        tts (TTSRuntimeSettings):
        turn (TurnRuntimeSettings):
    """

    llm: LLMRuntimeSettings
    local_vad: LocalVADRuntimeSettings
    locale: str
    stt: STTRuntimeSettings
    tts: TTSRuntimeSettings
    turn: TurnRuntimeSettings

    def to_dict(self) -> dict[str, Any]:
        llm = self.llm.to_dict()

        local_vad = self.local_vad.to_dict()

        locale = self.locale

        stt = self.stt.to_dict()

        tts = self.tts.to_dict()

        turn = self.turn.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "llm": llm,
                "local_vad": local_vad,
                "locale": locale,
                "stt": stt,
                "tts": tts,
                "turn": turn,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.llm_runtime_settings import LLMRuntimeSettings
        from ..models.local_vad_runtime_settings import LocalVADRuntimeSettings
        from ..models.stt_runtime_settings import STTRuntimeSettings
        from ..models.tts_runtime_settings import TTSRuntimeSettings
        from ..models.turn_runtime_settings import TurnRuntimeSettings

        d = dict(src_dict)
        llm = LLMRuntimeSettings.from_dict(d.pop("llm"))

        local_vad = LocalVADRuntimeSettings.from_dict(d.pop("local_vad"))

        locale = d.pop("locale")

        stt = STTRuntimeSettings.from_dict(d.pop("stt"))

        tts = TTSRuntimeSettings.from_dict(d.pop("tts"))

        turn = TurnRuntimeSettings.from_dict(d.pop("turn"))

        effective_voice_runtime = cls(
            llm=llm,
            local_vad=local_vad,
            locale=locale,
            stt=stt,
            tts=tts,
            turn=turn,
        )

        return effective_voice_runtime
