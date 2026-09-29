from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.cascade_tokenizer_strategy import CascadeTokenizerStrategy
from ..types import UNSET, Unset

T = TypeVar("T", bound="CascadeTokenizer")


@_attrs_define
class CascadeTokenizer:
    """
    Attributes:
        min_sentence_chars (int):
        min_phrase_chars (int | Unset):  Default: 10.
        strategy (CascadeTokenizerStrategy | Unset):  Default: CascadeTokenizerStrategy.SENTENCE.
    """

    min_sentence_chars: int
    min_phrase_chars: int | Unset = 10
    strategy: CascadeTokenizerStrategy | Unset = CascadeTokenizerStrategy.SENTENCE

    def to_dict(self) -> dict[str, Any]:
        min_sentence_chars = self.min_sentence_chars

        min_phrase_chars = self.min_phrase_chars

        strategy: str | Unset = UNSET
        if not isinstance(self.strategy, Unset):
            strategy = self.strategy.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "min_sentence_chars": min_sentence_chars,
            }
        )
        if min_phrase_chars is not UNSET:
            field_dict["min_phrase_chars"] = min_phrase_chars
        if strategy is not UNSET:
            field_dict["strategy"] = strategy

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        min_sentence_chars = d.pop("min_sentence_chars")

        min_phrase_chars = d.pop("min_phrase_chars", UNSET)

        _strategy = d.pop("strategy", UNSET)
        strategy: CascadeTokenizerStrategy | Unset
        if isinstance(_strategy, Unset):
            strategy = UNSET
        else:
            strategy = CascadeTokenizerStrategy(_strategy)

        cascade_tokenizer = cls(
            min_sentence_chars=min_sentence_chars,
            min_phrase_chars=min_phrase_chars,
            strategy=strategy,
        )

        return cascade_tokenizer
