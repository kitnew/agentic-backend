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

T = TypeVar("T", bound="TenantCredentialScopeWrite")


@_attrs_define
class TenantCredentialScopeWrite:
    """
    Attributes:
        tenant_id (str):
        type_ (Literal['tenant']):
    """

    tenant_id: str
    type_: Literal["tenant"]

    def to_dict(self) -> dict[str, Any]:
        tenant_id = self.tenant_id

        type_ = self.type_

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "tenant_id": tenant_id,
                "type": type_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        tenant_id = d.pop("tenant_id")

        type_ = cast(Literal["tenant"], d.pop("type"))
        if type_ != "tenant":
            raise ValueError(f"type must match const 'tenant', got '{type_}'")

        tenant_credential_scope_write = cls(
            tenant_id=tenant_id,
            type_=type_,
        )

        return tenant_credential_scope_write
