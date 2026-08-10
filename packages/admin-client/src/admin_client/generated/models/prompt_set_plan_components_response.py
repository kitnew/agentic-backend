from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.prompt_set_component_plan_response import (
        PromptSetComponentPlanResponse,
    )


T = TypeVar("T", bound="PromptSetPlanComponentsResponse")


@_attrs_define
class PromptSetPlanComponentsResponse:
    """
    Attributes:
        knowledge_base (PromptSetComponentPlanResponse):
        profile (PromptSetComponentPlanResponse):
        system (PromptSetComponentPlanResponse):
        tenant_prompt (PromptSetComponentPlanResponse):
    """

    knowledge_base: PromptSetComponentPlanResponse
    profile: PromptSetComponentPlanResponse
    system: PromptSetComponentPlanResponse
    tenant_prompt: PromptSetComponentPlanResponse
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        knowledge_base = self.knowledge_base.to_dict()

        profile = self.profile.to_dict()

        system = self.system.to_dict()

        tenant_prompt = self.tenant_prompt.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "knowledge_base": knowledge_base,
                "profile": profile,
                "system": system,
                "tenant_prompt": tenant_prompt,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.prompt_set_component_plan_response import (
            PromptSetComponentPlanResponse,
        )

        d = dict(src_dict)
        knowledge_base = PromptSetComponentPlanResponse.from_dict(
            d.pop("knowledge_base")
        )

        profile = PromptSetComponentPlanResponse.from_dict(d.pop("profile"))

        system = PromptSetComponentPlanResponse.from_dict(d.pop("system"))

        tenant_prompt = PromptSetComponentPlanResponse.from_dict(d.pop("tenant_prompt"))

        prompt_set_plan_components_response = cls(
            knowledge_base=knowledge_base,
            profile=profile,
            system=system,
            tenant_prompt=tenant_prompt,
        )

        prompt_set_plan_components_response.additional_properties = d
        return prompt_set_plan_components_response

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
