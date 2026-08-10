from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.knowledge_base_revision_response import KnowledgeBaseRevisionResponse
    from ..models.knowledge_document_summary_response import (
        KnowledgeDocumentSummaryResponse,
    )


T = TypeVar("T", bound="KnowledgeBaseStateResponse")


@_attrs_define
class KnowledgeBaseStateResponse:
    """
    Attributes:
        draft_revision (KnowledgeBaseRevisionResponse | None):
        latest_published_revision (KnowledgeBaseRevisionResponse | None):
        published_documents (list[KnowledgeDocumentSummaryResponse]):
        tenant_id (UUID):
    """

    draft_revision: KnowledgeBaseRevisionResponse | None
    latest_published_revision: KnowledgeBaseRevisionResponse | None
    published_documents: list[KnowledgeDocumentSummaryResponse]
    tenant_id: UUID
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.knowledge_base_revision_response import (
            KnowledgeBaseRevisionResponse,
        )

        draft_revision: dict[str, Any] | None
        if isinstance(self.draft_revision, KnowledgeBaseRevisionResponse):
            draft_revision = self.draft_revision.to_dict()
        else:
            draft_revision = self.draft_revision

        latest_published_revision: dict[str, Any] | None
        if isinstance(self.latest_published_revision, KnowledgeBaseRevisionResponse):
            latest_published_revision = self.latest_published_revision.to_dict()
        else:
            latest_published_revision = self.latest_published_revision

        published_documents = []
        for published_documents_item_data in self.published_documents:
            published_documents_item = published_documents_item_data.to_dict()
            published_documents.append(published_documents_item)

        tenant_id = str(self.tenant_id)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "draft_revision": draft_revision,
                "latest_published_revision": latest_published_revision,
                "published_documents": published_documents,
                "tenant_id": tenant_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.knowledge_base_revision_response import (
            KnowledgeBaseRevisionResponse,
        )
        from ..models.knowledge_document_summary_response import (
            KnowledgeDocumentSummaryResponse,
        )

        d = dict(src_dict)

        def _parse_draft_revision(data: object) -> KnowledgeBaseRevisionResponse | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                draft_revision_type_0 = KnowledgeBaseRevisionResponse.from_dict(data)

                return draft_revision_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(KnowledgeBaseRevisionResponse | None, data)

        draft_revision = _parse_draft_revision(d.pop("draft_revision"))

        def _parse_latest_published_revision(
            data: object,
        ) -> KnowledgeBaseRevisionResponse | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                latest_published_revision_type_0 = (
                    KnowledgeBaseRevisionResponse.from_dict(data)
                )

                return latest_published_revision_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(KnowledgeBaseRevisionResponse | None, data)

        latest_published_revision = _parse_latest_published_revision(
            d.pop("latest_published_revision")
        )

        published_documents = []
        _published_documents = d.pop("published_documents")
        for published_documents_item_data in _published_documents:
            published_documents_item = KnowledgeDocumentSummaryResponse.from_dict(
                published_documents_item_data
            )

            published_documents.append(published_documents_item)

        tenant_id = UUID(d.pop("tenant_id"))

        knowledge_base_state_response = cls(
            draft_revision=draft_revision,
            latest_published_revision=latest_published_revision,
            published_documents=published_documents,
            tenant_id=tenant_id,
        )

        knowledge_base_state_response.additional_properties = d
        return knowledge_base_state_response

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
