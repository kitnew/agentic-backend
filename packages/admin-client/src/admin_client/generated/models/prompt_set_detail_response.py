from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.prompt_set_composition_response import PromptSetCompositionResponse
    from ..models.prompt_set_revision_response import PromptSetRevisionResponse


T = TypeVar("T", bound="PromptSetDetailResponse")


@_attrs_define
class PromptSetDetailResponse:
    """
    Attributes:
        components (PromptSetCompositionResponse):
        revision (PromptSetRevisionResponse):
    """

    components: PromptSetCompositionResponse
    revision: PromptSetRevisionResponse
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        components = self.components.to_dict()

        revision = self.revision.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "components": components,
                "revision": revision,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.prompt_set_composition_response import (
            PromptSetCompositionResponse,
        )
        from ..models.prompt_set_revision_response import PromptSetRevisionResponse

        d = dict(src_dict)
        components = PromptSetCompositionResponse.from_dict(d.pop("components"))

        revision = PromptSetRevisionResponse.from_dict(d.pop("revision"))

        prompt_set_detail_response = cls(
            components=components,
            revision=revision,
        )

        prompt_set_detail_response.additional_properties = d
        return prompt_set_detail_response

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
