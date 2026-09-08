from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="CascadeTokenizer")


@_attrs_define
class CascadeTokenizer:
    """
    Attributes:
        min_sentence_chars (int):
    """

    min_sentence_chars: int

    def to_dict(self) -> dict[str, Any]:
        min_sentence_chars = self.min_sentence_chars

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "min_sentence_chars": min_sentence_chars,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        min_sentence_chars = d.pop("min_sentence_chars")

        cascade_tokenizer = cls(
            min_sentence_chars=min_sentence_chars,
        )

        return cascade_tokenizer
