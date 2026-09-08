from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="TTSDefaults")


@_attrs_define
class TTSDefaults:
    """
    Attributes:
        default_voice_id (str):
        deployment_ref (UUID):
    """

    default_voice_id: str
    deployment_ref: UUID

    def to_dict(self) -> dict[str, Any]:
        default_voice_id = self.default_voice_id

        deployment_ref = str(self.deployment_ref)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "default_voice_id": default_voice_id,
                "deployment_ref": deployment_ref,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        default_voice_id = d.pop("default_voice_id")

        deployment_ref = UUID(d.pop("deployment_ref"))

        tts_defaults = cls(
            default_voice_id=default_voice_id,
            deployment_ref=deployment_ref,
        )

        return tts_defaults
