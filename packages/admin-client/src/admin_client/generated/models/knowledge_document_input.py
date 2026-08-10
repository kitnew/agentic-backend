from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="KnowledgeDocumentInput")


@_attrs_define
class KnowledgeDocumentInput:
    """
    Attributes:
        key (str):
        content (str | Unset):  Default: ''.
        media_type (Literal['text/markdown'] | Unset):  Default: 'text/markdown'.
    """

    key: str
    content: str | Unset = ""
    media_type: Literal["text/markdown"] | Unset = "text/markdown"

    def to_dict(self) -> dict[str, Any]:
        key = self.key

        content = self.content

        media_type = self.media_type

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "key": key,
            }
        )
        if content is not UNSET:
            field_dict["content"] = content
        if media_type is not UNSET:
            field_dict["media_type"] = media_type

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        key = d.pop("key")

        content = d.pop("content", UNSET)

        media_type = cast(Literal["text/markdown"] | Unset, d.pop("media_type", UNSET))
        if media_type != "text/markdown" and not isinstance(media_type, Unset):
            raise ValueError(
                f"media_type must match const 'text/markdown', got '{media_type}'"
            )

        knowledge_document_input = cls(
            key=key,
            content=content,
            media_type=media_type,
        )

        return knowledge_document_input
