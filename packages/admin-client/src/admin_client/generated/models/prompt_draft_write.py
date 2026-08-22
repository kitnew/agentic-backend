from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="PromptDraftWrite")


@_attrs_define
class PromptDraftWrite:
    """
    Attributes:
        text (str):
    """

    text: str

    def to_dict(self) -> dict[str, Any]:
        text = self.text

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "text": text,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        text = d.pop("text")

        prompt_draft_write = cls(
            text=text,
        )

        return prompt_draft_write
