from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.prompt_set_detail_response import PromptSetDetailResponse


T = TypeVar("T", bound="PromptSetApplyResponse")


@_attrs_define
class PromptSetApplyResponse:
    """
    Attributes:
        changed (bool):
        prompt_set (PromptSetDetailResponse):
    """

    changed: bool
    prompt_set: PromptSetDetailResponse
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        changed = self.changed

        prompt_set = self.prompt_set.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "changed": changed,
                "prompt_set": prompt_set,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.prompt_set_detail_response import PromptSetDetailResponse

        d = dict(src_dict)
        changed = d.pop("changed")

        prompt_set = PromptSetDetailResponse.from_dict(d.pop("prompt_set"))

        prompt_set_apply_response = cls(
            changed=changed,
            prompt_set=prompt_set,
        )

        prompt_set_apply_response.additional_properties = d
        return prompt_set_apply_response

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
