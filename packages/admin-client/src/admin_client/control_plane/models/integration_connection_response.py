from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.integration_connection_response_config import (
        IntegrationConnectionResponseConfig,
    )


T = TypeVar("T", bound="IntegrationConnectionResponse")


@_attrs_define
class IntegrationConnectionResponse:
    """
    Attributes:
        config (IntegrationConnectionResponseConfig):
        created_at (datetime.datetime):
        credential_ref (None | UUID):
        enabled (bool):
        id (UUID):
        integration_kind (str):
        key (str):
        tenant_id (str):
        updated_at (datetime.datetime):
    """

    config: IntegrationConnectionResponseConfig
    created_at: datetime.datetime
    credential_ref: None | UUID
    enabled: bool
    id: UUID
    integration_kind: str
    key: str
    tenant_id: str
    updated_at: datetime.datetime

    def to_dict(self) -> dict[str, Any]:
        config = self.config.to_dict()

        created_at = self.created_at.isoformat()

        credential_ref: None | str
        if isinstance(self.credential_ref, UUID):
            credential_ref = str(self.credential_ref)
        else:
            credential_ref = self.credential_ref

        enabled = self.enabled

        id = str(self.id)

        integration_kind = self.integration_kind

        key = self.key

        tenant_id = self.tenant_id

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "config": config,
                "created_at": created_at,
                "credential_ref": credential_ref,
                "enabled": enabled,
                "id": id,
                "integration_kind": integration_kind,
                "key": key,
                "tenant_id": tenant_id,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.integration_connection_response_config import (
            IntegrationConnectionResponseConfig,
        )

        d = dict(src_dict)
        config = IntegrationConnectionResponseConfig.from_dict(d.pop("config"))

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        def _parse_credential_ref(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                credential_ref_type_0 = UUID(data)

                return credential_ref_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        credential_ref = _parse_credential_ref(d.pop("credential_ref"))

        enabled = d.pop("enabled")

        id = UUID(d.pop("id"))

        integration_kind = d.pop("integration_kind")

        key = d.pop("key")

        tenant_id = d.pop("tenant_id")

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        integration_connection_response = cls(
            config=config,
            created_at=created_at,
            credential_ref=credential_ref,
            enabled=enabled,
            id=id,
            integration_kind=integration_kind,
            key=key,
            tenant_id=tenant_id,
            updated_at=updated_at,
        )

        return integration_connection_response
