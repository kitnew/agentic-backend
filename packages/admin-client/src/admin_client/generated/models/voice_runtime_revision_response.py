from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.runtime_revision_status import RuntimeRevisionStatus

if TYPE_CHECKING:
    from ..models.effective_voice_runtime import EffectiveVoiceRuntime


T = TypeVar("T", bound="VoiceRuntimeRevisionResponse")


@_attrs_define
class VoiceRuntimeRevisionResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        effective_settings (EffectiveVoiceRuntime):
        id (UUID):
        platform_runtime_revision_id (UUID):
        published_at (datetime.datetime):
        revision_number (int):
        status (RuntimeRevisionStatus):
        tenant_id (UUID):
        tenant_runtime_revision_id (None | UUID):
    """

    created_at: datetime.datetime
    effective_settings: EffectiveVoiceRuntime
    id: UUID
    platform_runtime_revision_id: UUID
    published_at: datetime.datetime
    revision_number: int
    status: RuntimeRevisionStatus
    tenant_id: UUID
    tenant_runtime_revision_id: None | UUID
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        effective_settings = self.effective_settings.to_dict()

        id = str(self.id)

        platform_runtime_revision_id = str(self.platform_runtime_revision_id)

        published_at = self.published_at.isoformat()

        revision_number = self.revision_number

        status = self.status.value

        tenant_id = str(self.tenant_id)

        tenant_runtime_revision_id: None | str
        if isinstance(self.tenant_runtime_revision_id, UUID):
            tenant_runtime_revision_id = str(self.tenant_runtime_revision_id)
        else:
            tenant_runtime_revision_id = self.tenant_runtime_revision_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "effective_settings": effective_settings,
                "id": id,
                "platform_runtime_revision_id": platform_runtime_revision_id,
                "published_at": published_at,
                "revision_number": revision_number,
                "status": status,
                "tenant_id": tenant_id,
                "tenant_runtime_revision_id": tenant_runtime_revision_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.effective_voice_runtime import EffectiveVoiceRuntime

        d = dict(src_dict)
        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        effective_settings = EffectiveVoiceRuntime.from_dict(
            d.pop("effective_settings")
        )

        id = UUID(d.pop("id"))

        platform_runtime_revision_id = UUID(d.pop("platform_runtime_revision_id"))

        published_at = datetime.datetime.fromisoformat(d.pop("published_at"))

        revision_number = d.pop("revision_number")

        status = RuntimeRevisionStatus(d.pop("status"))

        tenant_id = UUID(d.pop("tenant_id"))

        def _parse_tenant_runtime_revision_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                tenant_runtime_revision_id_type_0 = UUID(data)

                return tenant_runtime_revision_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        tenant_runtime_revision_id = _parse_tenant_runtime_revision_id(
            d.pop("tenant_runtime_revision_id")
        )

        voice_runtime_revision_response = cls(
            created_at=created_at,
            effective_settings=effective_settings,
            id=id,
            platform_runtime_revision_id=platform_runtime_revision_id,
            published_at=published_at,
            revision_number=revision_number,
            status=status,
            tenant_id=tenant_id,
            tenant_runtime_revision_id=tenant_runtime_revision_id,
        )

        voice_runtime_revision_response.additional_properties = d
        return voice_runtime_revision_response

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
