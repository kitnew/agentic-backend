from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="CreateTextDraftRequest")


@_attrs_define
class CreateTextDraftRequest:
    """
    Attributes:
        text (str | Unset):  Default: ''.
    """

    text: str | Unset = ""

    def to_dict(self) -> dict[str, Any]:
        text = self.text

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if text is not UNSET:
            field_dict["text"] = text

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        text = d.pop("text", UNSET)

        create_text_draft_request = cls(
            text=text,
        )

        return create_text_draft_request
