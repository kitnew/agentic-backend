from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.voice_runtime_plan_status import VoiceRuntimePlanStatus

if TYPE_CHECKING:
    from ..models.effective_voice_runtime import EffectiveVoiceRuntime
    from ..models.voice_runtime_change import VoiceRuntimeChange
    from ..models.voice_runtime_revision_response import VoiceRuntimeRevisionResponse


T = TypeVar("T", bound="VoiceRuntimePlanResponse")


@_attrs_define
class VoiceRuntimePlanResponse:
    """
    Attributes:
        active_revision (None | VoiceRuntimeRevisionResponse):
        changes (list[VoiceRuntimeChange]):
        desired_settings (EffectiveVoiceRuntime):
        platform_runtime_revision_id (UUID):
        status (VoiceRuntimePlanStatus):
        tenant_runtime_revision_id (None | UUID):
    """

    active_revision: None | VoiceRuntimeRevisionResponse
    changes: list[VoiceRuntimeChange]
    desired_settings: EffectiveVoiceRuntime
    platform_runtime_revision_id: UUID
    status: VoiceRuntimePlanStatus
    tenant_runtime_revision_id: None | UUID
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.voice_runtime_revision_response import (
            VoiceRuntimeRevisionResponse,
        )

        active_revision: dict[str, Any] | None
        if isinstance(self.active_revision, VoiceRuntimeRevisionResponse):
            active_revision = self.active_revision.to_dict()
        else:
            active_revision = self.active_revision

        changes = []
        for changes_item_data in self.changes:
            changes_item = changes_item_data.to_dict()
            changes.append(changes_item)

        desired_settings = self.desired_settings.to_dict()

        platform_runtime_revision_id = str(self.platform_runtime_revision_id)

        status = self.status.value

        tenant_runtime_revision_id: None | str
        if isinstance(self.tenant_runtime_revision_id, UUID):
            tenant_runtime_revision_id = str(self.tenant_runtime_revision_id)
        else:
            tenant_runtime_revision_id = self.tenant_runtime_revision_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "active_revision": active_revision,
                "changes": changes,
                "desired_settings": desired_settings,
                "platform_runtime_revision_id": platform_runtime_revision_id,
                "status": status,
                "tenant_runtime_revision_id": tenant_runtime_revision_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.effective_voice_runtime import EffectiveVoiceRuntime
        from ..models.voice_runtime_change import VoiceRuntimeChange
        from ..models.voice_runtime_revision_response import (
            VoiceRuntimeRevisionResponse,
        )

        d = dict(src_dict)

        def _parse_active_revision(data: object) -> None | VoiceRuntimeRevisionResponse:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                active_revision_type_0 = VoiceRuntimeRevisionResponse.from_dict(data)

                return active_revision_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | VoiceRuntimeRevisionResponse, data)

        active_revision = _parse_active_revision(d.pop("active_revision"))

        changes = []
        _changes = d.pop("changes")
        for changes_item_data in _changes:
            changes_item = VoiceRuntimeChange.from_dict(changes_item_data)

            changes.append(changes_item)

        desired_settings = EffectiveVoiceRuntime.from_dict(d.pop("desired_settings"))

        platform_runtime_revision_id = UUID(d.pop("platform_runtime_revision_id"))

        status = VoiceRuntimePlanStatus(d.pop("status"))

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

        voice_runtime_plan_response = cls(
            active_revision=active_revision,
            changes=changes,
            desired_settings=desired_settings,
            platform_runtime_revision_id=platform_runtime_revision_id,
            status=status,
            tenant_runtime_revision_id=tenant_runtime_revision_id,
        )

        voice_runtime_plan_response.additional_properties = d
        return voice_runtime_plan_response

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
