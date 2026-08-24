from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="CatalogDescriptor")


@_attrs_define
class CatalogDescriptor:
    """
    Attributes:
        category (str):
        description (str):
        path (str):
        type_ (str):
    """

    category: str
    description: str
    path: str
    type_: str

    def to_dict(self) -> dict[str, Any]:
        category = self.category

        description = self.description

        path = self.path

        type_ = self.type_

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "category": category,
                "description": description,
                "path": path,
                "type": type_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        category = d.pop("category")

        description = d.pop("description")

        path = d.pop("path")

        type_ = d.pop("type")

        catalog_descriptor = cls(
            category=category,
            description=description,
            path=path,
            type_=type_,
        )

        return catalog_descriptor
