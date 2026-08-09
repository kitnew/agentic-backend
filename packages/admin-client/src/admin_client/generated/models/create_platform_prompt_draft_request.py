from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="CreatePlatformPromptDraftRequest")


@_attrs_define
class CreatePlatformPromptDraftRequest:
    """
    Attributes:
        key (str):
        text (str):
    """

    key: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        key = self.key

        text = self.text

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "key": key,
                "text": text,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        key = d.pop("key")

        text = d.pop("text")

        create_platform_prompt_draft_request = cls(
            key=key,
            text=text,
        )

        return create_platform_prompt_draft_request
