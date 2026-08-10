from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

T = TypeVar("T", bound="KnowledgeDocumentSummaryResponse")


@_attrs_define
class KnowledgeDocumentSummaryResponse:
    """
    Attributes:
        document_revision_number (int):
        key (str):
        media_type (str):
        position (int):
    """

    document_revision_number: int
    key: str
    media_type: str
    position: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        document_revision_number = self.document_revision_number

        key = self.key

        media_type = self.media_type

        position = self.position

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "document_revision_number": document_revision_number,
                "key": key,
                "media_type": media_type,
                "position": position,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        document_revision_number = d.pop("document_revision_number")

        key = d.pop("key")

        media_type = d.pop("media_type")

        position = d.pop("position")

        knowledge_document_summary_response = cls(
            document_revision_number=document_revision_number,
            key=key,
            media_type=media_type,
            position=position,
        )

        knowledge_document_summary_response.additional_properties = d
        return knowledge_document_summary_response

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
