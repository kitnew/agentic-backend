from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.catalog_status import CatalogStatus

if TYPE_CHECKING:
    from ..models.prompt_state_interaction_prompt import PromptStateInteractionPrompt


T = TypeVar("T", bound="InteractionModeConfiguration")


@_attrs_define
class InteractionModeConfiguration:
    """
    Attributes:
        description (str):
        key (str):
        name (str):
        prompt (PromptStateInteractionPrompt):
        status (CatalogStatus):
    """

    description: str
    key: str
    name: str
    prompt: PromptStateInteractionPrompt
    status: CatalogStatus

    def to_dict(self) -> dict[str, Any]:
        description = self.description

        key = self.key

        name = self.name

        prompt = self.prompt.to_dict()

        status = self.status.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "description": description,
                "key": key,
                "name": name,
                "prompt": prompt,
                "status": status,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.prompt_state_interaction_prompt import (
            PromptStateInteractionPrompt,
        )

        d = dict(src_dict)
        description = d.pop("description")

        key = d.pop("key")

        name = d.pop("name")

        prompt = PromptStateInteractionPrompt.from_dict(d.pop("prompt"))

        status = CatalogStatus(d.pop("status"))

        interaction_mode_configuration = cls(
            description=description,
            key=key,
            name=name,
            prompt=prompt,
            status=status,
        )

        return interaction_mode_configuration
