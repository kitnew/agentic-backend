from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.tenant_tts_runtime_override import TenantTTSRuntimeOverride


T = TypeVar("T", bound="TenantRuntimeOverride")


@_attrs_define
class TenantRuntimeOverride:
    """
    Attributes:
        tts (None | TenantTTSRuntimeOverride | Unset):
    """

    tts: None | TenantTTSRuntimeOverride | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.tenant_tts_runtime_override import TenantTTSRuntimeOverride

        tts: dict[str, Any] | None | Unset
        if isinstance(self.tts, Unset):
            tts = UNSET
        elif isinstance(self.tts, TenantTTSRuntimeOverride):
            tts = self.tts.to_dict()
        else:
            tts = self.tts

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if tts is not UNSET:
            field_dict["tts"] = tts

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.tenant_tts_runtime_override import TenantTTSRuntimeOverride

        d = dict(src_dict)

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

        tenant_runtime_override = cls(
            tts=tts,
        )

        return tenant_runtime_override
