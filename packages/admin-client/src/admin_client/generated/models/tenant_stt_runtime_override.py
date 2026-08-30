from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="TenantSTTRuntimeOverride")


@_attrs_define
class TenantSTTRuntimeOverride:
    """
    Attributes:
        keyterms (list[str] | Unset):
    """

    keyterms: list[str] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        keyterms: list[str] | Unset = UNSET
        if not isinstance(self.keyterms, Unset):
            keyterms = self.keyterms

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if keyterms is not UNSET:
            field_dict["keyterms"] = keyterms

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        keyterms = cast(list[str], d.pop("keyterms", UNSET))

        tenant_stt_runtime_override = cls(
            keyterms=keyterms,
        )

        return tenant_stt_runtime_override
