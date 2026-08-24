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

T = TypeVar("T", bound="HttpApiKeyHeaderAuthentication")


@_attrs_define
class HttpApiKeyHeaderAuthentication:
    """
    Attributes:
        header_name (str):
        type_ (Literal['api_key_header'] | Unset):  Default: 'api_key_header'.
    """

    header_name: str
    type_: Literal["api_key_header"] | Unset = "api_key_header"

    def to_dict(self) -> dict[str, Any]:
        header_name = self.header_name

        type_ = self.type_

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "header_name": header_name,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        header_name = d.pop("header_name")

        type_ = cast(Literal["api_key_header"] | Unset, d.pop("type", UNSET))
        if type_ != "api_key_header" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'api_key_header', got '{type_}'")

        http_api_key_header_authentication = cls(
            header_name=header_name,
            type_=type_,
        )

        return http_api_key_header_authentication
