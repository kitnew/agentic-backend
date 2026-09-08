from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="STTDefaults")


@_attrs_define
class STTDefaults:
    """
    Attributes:
        deployment_ref (UUID):
    """

    deployment_ref: UUID

    def to_dict(self) -> dict[str, Any]:
        deployment_ref = str(self.deployment_ref)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "deployment_ref": deployment_ref,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        deployment_ref = UUID(d.pop("deployment_ref"))

        stt_defaults = cls(
            deployment_ref=deployment_ref,
        )

        return stt_defaults
