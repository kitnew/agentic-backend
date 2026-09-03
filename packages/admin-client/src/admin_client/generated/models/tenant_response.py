from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.tenant_status import TenantStatus

T = TypeVar("T", bound="TenantResponse")


@_attrs_define
class TenantResponse:
    """
    Attributes:
        business_type (str):
        created_at (datetime.datetime):
        display_name (str):
        id (UUID):
        slug (str):
        status (TenantStatus):
        updated_at (datetime.datetime):
    """

    business_type: str
    created_at: datetime.datetime
    display_name: str
    id: UUID
    slug: str
    status: TenantStatus
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        business_type = self.business_type

        created_at = self.created_at.isoformat()

        display_name = self.display_name

        id = str(self.id)

        slug = self.slug

        status = self.status.value

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "business_type": business_type,
                "created_at": created_at,
                "display_name": display_name,
                "id": id,
                "slug": slug,
                "status": status,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        business_type = d.pop("business_type")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        display_name = d.pop("display_name")

        id = UUID(d.pop("id"))

        slug = d.pop("slug")

        status = TenantStatus(d.pop("status"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        tenant_response = cls(
            business_type=business_type,
            created_at=created_at,
            display_name=display_name,
            id=id,
            slug=slug,
            status=status,
            updated_at=updated_at,
        )

        tenant_response.additional_properties = d
        return tenant_response

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
