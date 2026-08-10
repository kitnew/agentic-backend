from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.knowledge_base_snapshot_response import KnowledgeBaseSnapshotResponse


T = TypeVar("T", bound="KnowledgeBasePublishResponse")


@_attrs_define
class KnowledgeBasePublishResponse:
    """
    Attributes:
        published (KnowledgeBaseSnapshotResponse):
    """

    published: KnowledgeBaseSnapshotResponse
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        published = self.published.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "published": published,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.knowledge_base_snapshot_response import (
            KnowledgeBaseSnapshotResponse,
        )

        d = dict(src_dict)
        published = KnowledgeBaseSnapshotResponse.from_dict(d.pop("published"))

        knowledge_base_publish_response = cls(
            published=published,
        )

        knowledge_base_publish_response.additional_properties = d
        return knowledge_base_publish_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
