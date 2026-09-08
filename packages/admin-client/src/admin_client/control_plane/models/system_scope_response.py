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

T = TypeVar("T", bound="SystemScopeResponse")


@_attrs_define
class SystemScopeResponse:
    """
    Attributes:
        type_ (Literal['system']):
    """

    type_: Literal["system"]

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
        type_ = cast(Literal["system"], d.pop("type"))
        if type_ != "system":
            raise ValueError(f"type must match const 'system', got '{type_}'")

        system_scope_response = cls(
            type_=type_,
        )

        return system_scope_response
