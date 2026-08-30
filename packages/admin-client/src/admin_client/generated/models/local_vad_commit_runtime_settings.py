from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="LocalVADCommitRuntimeSettings")


@_attrs_define
class LocalVADCommitRuntimeSettings:
    """
    Attributes:
        enabled (bool | Unset):  Default: False.
    """

    enabled: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        enabled = self.enabled

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if enabled is not UNSET:
            field_dict["enabled"] = enabled

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        enabled = d.pop("enabled", UNSET)

        local_vad_commit_runtime_settings = cls(
            enabled=enabled,
        )

        return local_vad_commit_runtime_settings
