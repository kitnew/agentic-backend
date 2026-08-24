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

from ..types import UNSET, Unset

T = TypeVar("T", bound="HttpAuthenticationNone")


@_attrs_define
class HttpAuthenticationNone:
    """
    Attributes:
        type_ (Literal['none'] | Unset):  Default: 'none'.
    """

    type_: Literal["none"] | Unset = "none"

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        type_ = cast(Literal["none"] | Unset, d.pop("type", UNSET))
        if type_ != "none" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'none', got '{type_}'")

        http_authentication_none = cls(
            type_=type_,
        )

        return http_authentication_none
