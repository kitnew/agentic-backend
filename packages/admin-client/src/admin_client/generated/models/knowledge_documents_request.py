from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.knowledge_document_input import KnowledgeDocumentInput


T = TypeVar("T", bound="KnowledgeDocumentsRequest")


@_attrs_define
class KnowledgeDocumentsRequest:
    """
    Attributes:
        documents (list[KnowledgeDocumentInput]):
    """

    documents: list[KnowledgeDocumentInput]

    def to_dict(self) -> dict[str, Any]:
        documents = []
        for documents_item_data in self.documents:
            documents_item = documents_item_data.to_dict()
            documents.append(documents_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "documents": documents,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.knowledge_document_input import KnowledgeDocumentInput

        d = dict(src_dict)
        documents = []
        _documents = d.pop("documents")
        for documents_item_data in _documents:
            documents_item = KnowledgeDocumentInput.from_dict(documents_item_data)

            documents.append(documents_item)

        knowledge_documents_request = cls(
            documents=documents,
        )

        return knowledge_documents_request
