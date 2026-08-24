from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="CapabilitySemanticDescriptor")


@_attrs_define
class CapabilitySemanticDescriptor:
    """
    Attributes:
        description (str):
        key (str):
        kind (str):
        tool_name (str):
        version (int):
    """

    description: str
    key: str
    kind: str
    tool_name: str
    version: int

    def to_dict(self) -> dict[str, Any]:
        description = self.description

        key = self.key

        kind = self.kind

        tool_name = self.tool_name

        version = self.version

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "description": description,
                "key": key,
                "kind": kind,
                "tool_name": tool_name,
                "version": version,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        description = d.pop("description")

        key = d.pop("key")

        kind = d.pop("kind")

        tool_name = d.pop("tool_name")

        version = d.pop("version")

        capability_semantic_descriptor = cls(
            description=description,
            key=key,
            kind=kind,
            tool_name=tool_name,
            version=version,
        )

        return capability_semantic_descriptor
