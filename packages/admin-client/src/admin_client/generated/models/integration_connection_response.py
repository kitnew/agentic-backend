from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.integration_kind import IntegrationKind
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.integration_connection_response_configuration import (
        IntegrationConnectionResponseConfiguration,
    )
    from ..models.integration_readiness import IntegrationReadiness


T = TypeVar("T", bound="IntegrationConnectionResponse")


@_attrs_define
class IntegrationConnectionResponse:
    """
    Attributes:
        configuration (IntegrationConnectionResponseConfiguration):
        created_at (datetime.datetime):
        enabled (bool):
        id (UUID):
        key (str):
        kind (IntegrationKind):
        readiness (IntegrationReadiness):
        revision (int):
        tenant_id (UUID):
        updated_at (datetime.datetime):
        credential_fingerprint (None | str | Unset):
        credential_status (None | str | Unset):
        credential_version (int | None | Unset):
    """

    configuration: IntegrationConnectionResponseConfiguration
    created_at: datetime.datetime
    enabled: bool
    id: UUID
    key: str
    kind: IntegrationKind
    readiness: IntegrationReadiness
    revision: int
    tenant_id: UUID
    updated_at: datetime.datetime
    credential_fingerprint: None | str | Unset = UNSET
    credential_status: None | str | Unset = UNSET
    credential_version: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        configuration = self.configuration.to_dict()

        created_at = self.created_at.isoformat()

        enabled = self.enabled

        id = str(self.id)

        key = self.key

        kind = self.kind.value

        readiness = self.readiness.to_dict()

        revision = self.revision

        tenant_id = str(self.tenant_id)

        updated_at = self.updated_at.isoformat()

        credential_fingerprint: None | str | Unset
        if isinstance(self.credential_fingerprint, Unset):
            credential_fingerprint = UNSET
        else:
            credential_fingerprint = self.credential_fingerprint

        credential_status: None | str | Unset
        if isinstance(self.credential_status, Unset):
            credential_status = UNSET
        else:
            credential_status = self.credential_status

        credential_version: int | None | Unset
        if isinstance(self.credential_version, Unset):
            credential_version = UNSET
        else:
            credential_version = self.credential_version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "configuration": configuration,
                "created_at": created_at,
                "enabled": enabled,
                "id": id,
                "key": key,
                "kind": kind,
                "readiness": readiness,
                "revision": revision,
                "tenant_id": tenant_id,
                "updated_at": updated_at,
            }
        )
        if credential_fingerprint is not UNSET:
            field_dict["credential_fingerprint"] = credential_fingerprint
        if credential_status is not UNSET:
            field_dict["credential_status"] = credential_status
        if credential_version is not UNSET:
            field_dict["credential_version"] = credential_version

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.integration_connection_response_configuration import (
            IntegrationConnectionResponseConfiguration,
        )
        from ..models.integration_readiness import IntegrationReadiness

        d = dict(src_dict)
        configuration = IntegrationConnectionResponseConfiguration.from_dict(
            d.pop("configuration")
        )

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        enabled = d.pop("enabled")

        id = UUID(d.pop("id"))

        key = d.pop("key")

        kind = IntegrationKind(d.pop("kind"))

        readiness = IntegrationReadiness.from_dict(d.pop("readiness"))

        revision = d.pop("revision")

        tenant_id = UUID(d.pop("tenant_id"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        def _parse_credential_fingerprint(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        credential_fingerprint = _parse_credential_fingerprint(
            d.pop("credential_fingerprint", UNSET)
        )

        def _parse_credential_status(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        credential_status = _parse_credential_status(d.pop("credential_status", UNSET))

        def _parse_credential_version(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        credential_version = _parse_credential_version(
            d.pop("credential_version", UNSET)
        )

        integration_connection_response = cls(
            configuration=configuration,
            created_at=created_at,
            enabled=enabled,
            id=id,
            key=key,
            kind=kind,
            readiness=readiness,
            revision=revision,
            tenant_id=tenant_id,
            updated_at=updated_at,
            credential_fingerprint=credential_fingerprint,
            credential_status=credential_status,
            credential_version=credential_version,
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
