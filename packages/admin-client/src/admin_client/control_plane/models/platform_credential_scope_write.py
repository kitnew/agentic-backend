from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="PlatformCredentialScopeWrite")


@_attrs_define
class PlatformCredentialScopeWrite:
    """
    Attributes:
        type_ (Literal['platform']):
    """

    type_: Literal["platform"]

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "type": type_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        type_ = cast(Literal["platform"], d.pop("type"))
        if type_ != "platform":
            raise ValueError(f"type must match const 'platform', got '{type_}'")

        platform_credential_scope_write = cls(
            type_=type_,
        )

        return platform_credential_scope_write
