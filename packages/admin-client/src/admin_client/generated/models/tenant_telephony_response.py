from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.telephony_readiness import TelephonyReadiness
    from ..models.tenant_telephony_config import TenantTelephonyConfig


T = TypeVar("T", bound="TenantTelephonyResponse")


@_attrs_define
class TenantTelephonyResponse:
    """
    Attributes:
        desired (TenantTelephonyConfig):
        draft_revision_id (None | UUID):
        draft_version (int | None):
        last_error (None | str):
        last_reconciled_at (datetime.datetime | None):
        provisioning_status (str):
        published_revision_id (None | UUID):
        readiness (TelephonyReadiness):
        tenant_id (UUID):
    """

    desired: TenantTelephonyConfig
    draft_revision_id: None | UUID
    draft_version: int | None
    last_error: None | str
    last_reconciled_at: datetime.datetime | None
    provisioning_status: str
    published_revision_id: None | UUID
    readiness: TelephonyReadiness
    tenant_id: UUID
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        desired = self.desired.to_dict()

        draft_revision_id: None | str
        if isinstance(self.draft_revision_id, UUID):
            draft_revision_id = str(self.draft_revision_id)
        else:
            draft_revision_id = self.draft_revision_id

        draft_version: int | None
        draft_version = self.draft_version

        last_error: None | str
        last_error = self.last_error

        last_reconciled_at: None | str
        if isinstance(self.last_reconciled_at, datetime.datetime):
            last_reconciled_at = self.last_reconciled_at.isoformat()
        else:
            last_reconciled_at = self.last_reconciled_at

        provisioning_status = self.provisioning_status

        published_revision_id: None | str
        if isinstance(self.published_revision_id, UUID):
            published_revision_id = str(self.published_revision_id)
        else:
            published_revision_id = self.published_revision_id

        readiness = self.readiness.to_dict()

        tenant_id = str(self.tenant_id)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "desired": desired,
                "draft_revision_id": draft_revision_id,
                "draft_version": draft_version,
                "last_error": last_error,
                "last_reconciled_at": last_reconciled_at,
                "provisioning_status": provisioning_status,
                "published_revision_id": published_revision_id,
                "readiness": readiness,
                "tenant_id": tenant_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.telephony_readiness import TelephonyReadiness
        from ..models.tenant_telephony_config import TenantTelephonyConfig

        d = dict(src_dict)
        desired = TenantTelephonyConfig.from_dict(d.pop("desired"))

        def _parse_draft_revision_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                draft_revision_id_type_0 = UUID(data)

                return draft_revision_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        draft_revision_id = _parse_draft_revision_id(d.pop("draft_revision_id"))

        def _parse_draft_version(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        draft_version = _parse_draft_version(d.pop("draft_version"))

        def _parse_last_error(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        last_error = _parse_last_error(d.pop("last_error"))

        def _parse_last_reconciled_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_reconciled_at_type_0 = datetime.datetime.fromisoformat(data)

                return last_reconciled_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        last_reconciled_at = _parse_last_reconciled_at(d.pop("last_reconciled_at"))

        provisioning_status = d.pop("provisioning_status")

        def _parse_published_revision_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                published_revision_id_type_0 = UUID(data)

                return published_revision_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        published_revision_id = _parse_published_revision_id(
            d.pop("published_revision_id")
        )

        readiness = TelephonyReadiness.from_dict(d.pop("readiness"))

        tenant_id = UUID(d.pop("tenant_id"))

        tenant_telephony_response = cls(
            desired=desired,
            draft_revision_id=draft_revision_id,
            draft_version=draft_version,
            last_error=last_error,
            last_reconciled_at=last_reconciled_at,
            provisioning_status=provisioning_status,
            published_revision_id=published_revision_id,
            readiness=readiness,
            tenant_id=tenant_id,
        )

        tenant_telephony_response.additional_properties = d
        return tenant_telephony_response

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
