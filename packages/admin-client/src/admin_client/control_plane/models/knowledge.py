from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="Knowledge")


@_attrs_define
class Knowledge:
    """
    Attributes:
        content (str):
    """

    content: str

    def to_dict(self) -> dict[str, Any]:
        content = self.content

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "content": content,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        content = d.pop("content")

        knowledge = cls(
            content=content,
        )

        return knowledge
