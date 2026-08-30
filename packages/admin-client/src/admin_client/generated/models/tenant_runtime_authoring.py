from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.tenant_llm_runtime_override import TenantLLMRuntimeOverride
    from ..models.tenant_stt_runtime_override import TenantSTTRuntimeOverride
    from ..models.tenant_tts_runtime_override import TenantTTSRuntimeOverride


T = TypeVar("T", bound="TenantRuntimeAuthoring")


@_attrs_define
class TenantRuntimeAuthoring:
    """
    Attributes:
        llm (None | TenantLLMRuntimeOverride | Unset):
        stt (None | TenantSTTRuntimeOverride | Unset):
        tts (None | TenantTTSRuntimeOverride | Unset):
    """

    llm: None | TenantLLMRuntimeOverride | Unset = UNSET
    stt: None | TenantSTTRuntimeOverride | Unset = UNSET
    tts: None | TenantTTSRuntimeOverride | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.tenant_llm_runtime_override import TenantLLMRuntimeOverride
        from ..models.tenant_stt_runtime_override import TenantSTTRuntimeOverride
        from ..models.tenant_tts_runtime_override import TenantTTSRuntimeOverride

        llm: dict[str, Any] | None | Unset
        if isinstance(self.llm, Unset):
            llm = UNSET
        elif isinstance(self.llm, TenantLLMRuntimeOverride):
            llm = self.llm.to_dict()
        else:
            llm = self.llm

        stt: dict[str, Any] | None | Unset
        if isinstance(self.stt, Unset):
            stt = UNSET
        elif isinstance(self.stt, TenantSTTRuntimeOverride):
            stt = self.stt.to_dict()
        else:
            stt = self.stt

        tts: dict[str, Any] | None | Unset
        if isinstance(self.tts, Unset):
            tts = UNSET
        elif isinstance(self.tts, TenantTTSRuntimeOverride):
            tts = self.tts.to_dict()
        else:
            tts = self.tts

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if llm is not UNSET:
            field_dict["llm"] = llm
        if stt is not UNSET:
            field_dict["stt"] = stt
        if tts is not UNSET:
            field_dict["tts"] = tts

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.tenant_llm_runtime_override import TenantLLMRuntimeOverride
        from ..models.tenant_stt_runtime_override import TenantSTTRuntimeOverride
        from ..models.tenant_tts_runtime_override import TenantTTSRuntimeOverride

        d = dict(src_dict)

        def _parse_llm(data: object) -> None | TenantLLMRuntimeOverride | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                llm_type_0 = TenantLLMRuntimeOverride.from_dict(data)

                return llm_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TenantLLMRuntimeOverride | Unset, data)

        llm = _parse_llm(d.pop("llm", UNSET))

        def _parse_stt(data: object) -> None | TenantSTTRuntimeOverride | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                stt_type_0 = TenantSTTRuntimeOverride.from_dict(data)

                return stt_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TenantSTTRuntimeOverride | Unset, data)

        stt = _parse_stt(d.pop("stt", UNSET))

        def _parse_tts(data: object) -> None | TenantTTSRuntimeOverride | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                tts_type_0 = TenantTTSRuntimeOverride.from_dict(data)

                return tts_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TenantTTSRuntimeOverride | Unset, data)

        tts = _parse_tts(d.pop("tts", UNSET))

        tenant_runtime_authoring = cls(
            llm=llm,
            stt=stt,
            tts=tts,
        )

        return tenant_runtime_authoring
