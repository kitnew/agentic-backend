from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.prompt_set_plan_response_status import PromptSetPlanResponseStatus

if TYPE_CHECKING:
    from ..models.prompt_set_plan_components_response import (
        PromptSetPlanComponentsResponse,
    )


T = TypeVar("T", bound="PromptSetPlanResponse")


@_attrs_define
class PromptSetPlanResponse:
    """
    Attributes:
        active_revision_number (int | None):
        components (PromptSetPlanComponentsResponse):
        status (PromptSetPlanResponseStatus):
        tenant_id (UUID):
    """

    active_revision_number: int | None
    components: PromptSetPlanComponentsResponse
    status: PromptSetPlanResponseStatus
    tenant_id: UUID
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        active_revision_number: int | None
        active_revision_number = self.active_revision_number

        components = self.components.to_dict()

        status = self.status.value

        tenant_id = str(self.tenant_id)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "active_revision_number": active_revision_number,
                "components": components,
                "status": status,
                "tenant_id": tenant_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.prompt_set_plan_components_response import (
            PromptSetPlanComponentsResponse,
        )

        d = dict(src_dict)

        def _parse_active_revision_number(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        active_revision_number = _parse_active_revision_number(
            d.pop("active_revision_number")
        )

        components = PromptSetPlanComponentsResponse.from_dict(d.pop("components"))

        status = PromptSetPlanResponseStatus(d.pop("status"))

        tenant_id = UUID(d.pop("tenant_id"))

        prompt_set_plan_response = cls(
            active_revision_number=active_revision_number,
            components=components,
            status=status,
            tenant_id=tenant_id,
        )

        prompt_set_plan_response.additional_properties = d
        return prompt_set_plan_response

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
