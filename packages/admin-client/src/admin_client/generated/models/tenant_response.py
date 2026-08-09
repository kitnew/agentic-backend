from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
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
        active_config_revision_id (None | UUID):
        active_prompt_set_revision_id (None | UUID):
        business_type (str):
        created_at (datetime.datetime):
        display_name (str):
        id (UUID):
        slug (str):
        status (TenantStatus):
        updated_at (datetime.datetime):
    """

    active_config_revision_id: None | UUID
    active_prompt_set_revision_id: None | UUID
    business_type: str
    created_at: datetime.datetime
    display_name: str
    id: UUID
    slug: str
    status: TenantStatus
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        active_config_revision_id: None | str
        if isinstance(self.active_config_revision_id, UUID):
            active_config_revision_id = str(self.active_config_revision_id)
        else:
            active_config_revision_id = self.active_config_revision_id

        active_prompt_set_revision_id: None | str
        if isinstance(self.active_prompt_set_revision_id, UUID):
            active_prompt_set_revision_id = str(self.active_prompt_set_revision_id)
        else:
            active_prompt_set_revision_id = self.active_prompt_set_revision_id

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
                "active_config_revision_id": active_config_revision_id,
                "active_prompt_set_revision_id": active_prompt_set_revision_id,
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

        def _parse_active_config_revision_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                active_config_revision_id_type_0 = UUID(data)

                return active_config_revision_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        active_config_revision_id = _parse_active_config_revision_id(
            d.pop("active_config_revision_id")
        )

        def _parse_active_prompt_set_revision_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                active_prompt_set_revision_id_type_0 = UUID(data)

                return active_prompt_set_revision_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        active_prompt_set_revision_id = _parse_active_prompt_set_revision_id(
            d.pop("active_prompt_set_revision_id")
        )

        business_type = d.pop("business_type")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        display_name = d.pop("display_name")

        id = UUID(d.pop("id"))

        slug = d.pop("slug")

        status = TenantStatus(d.pop("status"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        tenant_response = cls(
            active_config_revision_id=active_config_revision_id,
            active_prompt_set_revision_id=active_prompt_set_revision_id,
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
