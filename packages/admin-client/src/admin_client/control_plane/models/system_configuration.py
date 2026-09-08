from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.llm_defaults import LLMDefaults
    from ..models.policies import Policies
    from ..models.realtime_defaults import RealtimeDefaults
    from ..models.stt_defaults import STTDefaults
    from ..models.tts_defaults import TTSDefaults


T = TypeVar("T", bound="SystemConfiguration")


@_attrs_define
class SystemConfiguration:
    """
    Attributes:
        llm_defaults (LLMDefaults):
        policies (Policies):
        realtime_defaults (RealtimeDefaults):
        stt_defaults (STTDefaults):
        tts_defaults (TTSDefaults):
    """

    llm_defaults: LLMDefaults
    policies: Policies
    realtime_defaults: RealtimeDefaults
    stt_defaults: STTDefaults
    tts_defaults: TTSDefaults

    def to_dict(self) -> dict[str, Any]:
        llm_defaults = self.llm_defaults.to_dict()

        policies = self.policies.to_dict()

        realtime_defaults = self.realtime_defaults.to_dict()

        stt_defaults = self.stt_defaults.to_dict()

        tts_defaults = self.tts_defaults.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "llm_defaults": llm_defaults,
                "policies": policies,
                "realtime_defaults": realtime_defaults,
                "stt_defaults": stt_defaults,
                "tts_defaults": tts_defaults,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.llm_defaults import LLMDefaults
        from ..models.policies import Policies
        from ..models.realtime_defaults import RealtimeDefaults
        from ..models.stt_defaults import STTDefaults
        from ..models.tts_defaults import TTSDefaults

        d = dict(src_dict)
        llm_defaults = LLMDefaults.from_dict(d.pop("llm_defaults"))

        policies = Policies.from_dict(d.pop("policies"))

        realtime_defaults = RealtimeDefaults.from_dict(d.pop("realtime_defaults"))

        stt_defaults = STTDefaults.from_dict(d.pop("stt_defaults"))

        tts_defaults = TTSDefaults.from_dict(d.pop("tts_defaults"))

        system_configuration = cls(
            llm_defaults=llm_defaults,
            policies=policies,
            realtime_defaults=realtime_defaults,
            stt_defaults=stt_defaults,
            tts_defaults=tts_defaults,
        )

        return system_configuration
