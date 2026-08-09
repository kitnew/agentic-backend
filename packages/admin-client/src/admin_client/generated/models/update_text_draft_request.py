from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="UpdateTextDraftRequest")


@_attrs_define
class UpdateTextDraftRequest:
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

        update_text_draft_request = cls(
            text=text,
        )

        return update_text_draft_request
