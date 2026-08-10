from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="TenantTTSRuntimeOverride")


@_attrs_define
class TenantTTSRuntimeOverride:
    """
    Attributes:
        voice_id (str):
    """

    voice_id: str

    def to_dict(self) -> dict[str, Any]:
        voice_id = self.voice_id

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "voice_id": voice_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        voice_id = d.pop("voice_id")

        tenant_tts_runtime_override = cls(
            voice_id=voice_id,
        )

        return tenant_tts_runtime_override
