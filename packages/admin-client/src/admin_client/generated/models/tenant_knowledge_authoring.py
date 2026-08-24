from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="TenantKnowledgeAuthoring")


@_attrs_define
class TenantKnowledgeAuthoring:
    """
    Attributes:
        content (str | Unset):  Default: ''.
    """

    content: str | Unset = ""

    def to_dict(self) -> dict[str, Any]:
        content = self.content

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if content is not UNSET:
            field_dict["content"] = content

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        content = d.pop("content", UNSET)

        tenant_knowledge_authoring = cls(
            content=content,
        )

        return tenant_knowledge_authoring
