from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.prompt_set_component_response import PromptSetComponentResponse


T = TypeVar("T", bound="PromptSetComponentPlanResponse")


@_attrs_define
class PromptSetComponentPlanResponse:
    """
    Attributes:
        active (None | PromptSetComponentResponse):
        changed (bool):
        desired (PromptSetComponentResponse):
        reason (None | str | Unset):
    """

    active: None | PromptSetComponentResponse
    changed: bool
    desired: PromptSetComponentResponse
    reason: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.prompt_set_component_response import PromptSetComponentResponse

        active: dict[str, Any] | None
        if isinstance(self.active, PromptSetComponentResponse):
            active = self.active.to_dict()
        else:
            active = self.active

        changed = self.changed

        desired = self.desired.to_dict()

        reason: None | str | Unset
        if isinstance(self.reason, Unset):
            reason = UNSET
        else:
            reason = self.reason

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "active": active,
                "changed": changed,
                "desired": desired,
            }
        )
        if reason is not UNSET:
            field_dict["reason"] = reason

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.prompt_set_component_response import PromptSetComponentResponse

        d = dict(src_dict)

        def _parse_active(data: object) -> None | PromptSetComponentResponse:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                active_type_0 = PromptSetComponentResponse.from_dict(data)

                return active_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PromptSetComponentResponse, data)

        active = _parse_active(d.pop("active"))

        changed = d.pop("changed")

        desired = PromptSetComponentResponse.from_dict(d.pop("desired"))

        def _parse_reason(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reason = _parse_reason(d.pop("reason", UNSET))

        prompt_set_component_plan_response = cls(
            active=active,
            changed=changed,
            desired=desired,
            reason=reason,
        )

        prompt_set_component_plan_response.additional_properties = d
        return prompt_set_component_plan_response

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
