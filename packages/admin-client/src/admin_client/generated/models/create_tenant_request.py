from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.tenant_status import TenantStatus
from ..types import UNSET, Unset

T = TypeVar("T", bound="CreateTenantRequest")


@_attrs_define
class CreateTenantRequest:
    """
    Attributes:
        business_type (str):
        display_name (str):
        slug (str):
        status (TenantStatus | Unset):
    """

    business_type: str
    display_name: str
    slug: str
    status: TenantStatus | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        business_type = self.business_type

        display_name = self.display_name

        slug = self.slug

        status: str | Unset = UNSET
        if not isinstance(self.status, Unset):
            status = self.status.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "business_type": business_type,
                "display_name": display_name,
                "slug": slug,
            }
        )
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        business_type = d.pop("business_type")

        display_name = d.pop("display_name")

        slug = d.pop("slug")

        _status = d.pop("status", UNSET)
        status: TenantStatus | Unset
        if isinstance(_status, Unset):
            status = UNSET
        else:
            status = TenantStatus(_status)

        create_tenant_request = cls(
            business_type=business_type,
            display_name=display_name,
            slug=slug,
            status=status,
        )

        create_tenant_request.additional_properties = d
        return create_tenant_request

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
