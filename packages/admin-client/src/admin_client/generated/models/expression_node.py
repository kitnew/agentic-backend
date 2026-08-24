from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="ExpressionNode")


@_attrs_define
class ExpressionNode:
    """
    Attributes:
        expr (str):
    """

    expr: str

    def to_dict(self) -> dict[str, Any]:
        expr = self.expr

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "$expr": expr,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        expr = d.pop("$expr")

        expression_node = cls(
            expr=expr,
        )

        return expression_node
