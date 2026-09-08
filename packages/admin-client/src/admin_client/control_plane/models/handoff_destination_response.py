from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="HandoffDestinationResponse")


@_attrs_define
class HandoffDestinationResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        description (str):
        enabled (bool):
        id (UUID):
        key (str):
        phone_number (str):
        tenant_id (str):
        updated_at (datetime.datetime):
    """

    created_at: datetime.datetime
    description: str
    enabled: bool
    id: UUID
    key: str
    phone_number: str
    tenant_id: str
    updated_at: datetime.datetime

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        description = self.description

        enabled = self.enabled

        id = str(self.id)

        key = self.key

        phone_number = self.phone_number

        tenant_id = self.tenant_id

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "created_at": created_at,
                "description": description,
                "enabled": enabled,
                "id": id,
                "key": key,
                "phone_number": phone_number,
                "tenant_id": tenant_id,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        description = d.pop("description")

        enabled = d.pop("enabled")

        id = UUID(d.pop("id"))

        key = d.pop("key")

        phone_number = d.pop("phone_number")

        tenant_id = d.pop("tenant_id")

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        handoff_destination_response = cls(
            created_at=created_at,
            description=description,
            enabled=enabled,
            id=id,
            key=key,
            phone_number=phone_number,
            tenant_id=tenant_id,
            updated_at=updated_at,
        )

        return handoff_destination_response
