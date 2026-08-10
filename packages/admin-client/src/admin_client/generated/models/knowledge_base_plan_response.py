from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.knowledge_base_plan_response_status import KnowledgeBasePlanResponseStatus

if TYPE_CHECKING:
    from ..models.knowledge_document_plan_response import KnowledgeDocumentPlanResponse


T = TypeVar("T", bound="KnowledgeBasePlanResponse")


@_attrs_define
class KnowledgeBasePlanResponse:
    """
    Attributes:
        base_version (int):
        create_count (int):
        documents (list[KnowledgeDocumentPlanResponse]):
        remove_count (int):
        reuse_count (int):
        status (KnowledgeBasePlanResponseStatus):
        tenant_id (UUID):
        update_draft (bool):
    """

    base_version: int
    create_count: int
    documents: list[KnowledgeDocumentPlanResponse]
    remove_count: int
    reuse_count: int
    status: KnowledgeBasePlanResponseStatus
    tenant_id: UUID
    update_draft: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        base_version = self.base_version

        create_count = self.create_count

        documents = []
        for documents_item_data in self.documents:
            documents_item = documents_item_data.to_dict()
            documents.append(documents_item)

        remove_count = self.remove_count

        reuse_count = self.reuse_count

        status = self.status.value

        tenant_id = str(self.tenant_id)

        update_draft = self.update_draft

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "base_version": base_version,
                "create_count": create_count,
                "documents": documents,
                "remove_count": remove_count,
                "reuse_count": reuse_count,
                "status": status,
                "tenant_id": tenant_id,
                "update_draft": update_draft,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.knowledge_document_plan_response import (
            KnowledgeDocumentPlanResponse,
        )

        d = dict(src_dict)
        base_version = d.pop("base_version")

        create_count = d.pop("create_count")

        documents = []
        _documents = d.pop("documents")
        for documents_item_data in _documents:
            documents_item = KnowledgeDocumentPlanResponse.from_dict(
                documents_item_data
            )

            documents.append(documents_item)

        remove_count = d.pop("remove_count")

        reuse_count = d.pop("reuse_count")

        status = KnowledgeBasePlanResponseStatus(d.pop("status"))

        tenant_id = UUID(d.pop("tenant_id"))

        update_draft = d.pop("update_draft")

        knowledge_base_plan_response = cls(
            base_version=base_version,
            create_count=create_count,
            documents=documents,
            remove_count=remove_count,
            reuse_count=reuse_count,
            status=status,
            tenant_id=tenant_id,
            update_draft=update_draft,
        )

        knowledge_base_plan_response.additional_properties = d
        return knowledge_base_plan_response

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
