from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.integration_connection_status import IntegrationConnectionStatus
from ..models.integration_provider import IntegrationProvider

T = TypeVar("T", bound="IntegrationConnectionResponse")


@_attrs_define
class IntegrationConnectionResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        credential_ref (str):
        id (UUID):
        key (str):
        provider (IntegrationProvider):
        status (IntegrationConnectionStatus):
        tenant_id (UUID):
        updated_at (datetime.datetime):
    """

    created_at: datetime.datetime
    credential_ref: str
    id: UUID
    key: str
    provider: IntegrationProvider
    status: IntegrationConnectionStatus
    tenant_id: UUID
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        credential_ref = self.credential_ref

        id = str(self.id)

        key = self.key

        provider = self.provider.value

        status = self.status.value

        tenant_id = str(self.tenant_id)

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "credential_ref": credential_ref,
                "id": id,
                "key": key,
                "provider": provider,
                "status": status,
                "tenant_id": tenant_id,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        credential_ref = d.pop("credential_ref")

        id = UUID(d.pop("id"))

        key = d.pop("key")

        provider = IntegrationProvider(d.pop("provider"))

        status = IntegrationConnectionStatus(d.pop("status"))

        tenant_id = UUID(d.pop("tenant_id"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        integration_connection_response = cls(
            created_at=created_at,
            credential_ref=credential_ref,
            id=id,
            key=key,
            provider=provider,
            status=status,
            tenant_id=tenant_id,
            updated_at=updated_at,
        )

        integration_connection_response.additional_properties = d
        return integration_connection_response

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
