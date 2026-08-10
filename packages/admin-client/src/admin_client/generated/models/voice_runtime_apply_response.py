from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.voice_runtime_revision_response import VoiceRuntimeRevisionResponse


T = TypeVar("T", bound="VoiceRuntimeApplyResponse")


@_attrs_define
class VoiceRuntimeApplyResponse:
    """
    Attributes:
        changed (bool):
        voice_runtime (VoiceRuntimeRevisionResponse):
    """

    changed: bool
    voice_runtime: VoiceRuntimeRevisionResponse
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        changed = self.changed

        voice_runtime = self.voice_runtime.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "changed": changed,
                "voice_runtime": voice_runtime,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.voice_runtime_revision_response import (
            VoiceRuntimeRevisionResponse,
        )

        d = dict(src_dict)
        changed = d.pop("changed")

        voice_runtime = VoiceRuntimeRevisionResponse.from_dict(d.pop("voice_runtime"))

        voice_runtime_apply_response = cls(
            changed=changed,
            voice_runtime=voice_runtime,
        )

        voice_runtime_apply_response.additional_properties = d
        return voice_runtime_apply_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
