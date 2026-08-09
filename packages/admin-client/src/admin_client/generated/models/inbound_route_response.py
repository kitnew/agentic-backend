from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

T = TypeVar("T", bound="InboundRouteResponse")


@_attrs_define
class InboundRouteResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        enabled (bool):
        id (UUID):
        normalized_did (str):
        tenant_id (UUID):
        updated_at (datetime.datetime):
    """

    created_at: datetime.datetime
    enabled: bool
    id: UUID
    normalized_did: str
    tenant_id: UUID
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        enabled = self.enabled

        id = str(self.id)

        normalized_did = self.normalized_did

        tenant_id = str(self.tenant_id)

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "enabled": enabled,
                "id": id,
                "normalized_did": normalized_did,
                "tenant_id": tenant_id,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        enabled = d.pop("enabled")

        id = UUID(d.pop("id"))

        normalized_did = d.pop("normalized_did")

        tenant_id = UUID(d.pop("tenant_id"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        inbound_route_response = cls(
            created_at=created_at,
            enabled=enabled,
            id=id,
            normalized_did=normalized_did,
            tenant_id=tenant_id,
            updated_at=updated_at,
        )

        inbound_route_response.additional_properties = d
        return inbound_route_response

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
