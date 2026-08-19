from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

T = TypeVar("T", bound="IntegrationTestResponse")


@_attrs_define
class IntegrationTestResponse:
    """
    Attributes:
        credential_version (int):
        integration_id (UUID):
        status (str):
    """

    credential_version: int
    integration_id: UUID
    status: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        credential_version = self.credential_version

        integration_id = str(self.integration_id)

        status = self.status

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "credential_version": credential_version,
                "integration_id": integration_id,
                "status": status,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        credential_version = d.pop("credential_version")

        integration_id = UUID(d.pop("integration_id"))

        status = d.pop("status")

        integration_test_response = cls(
            credential_version=credential_version,
            integration_id=integration_id,
            status=status,
        )

        integration_test_response.additional_properties = d
        return integration_test_response

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
