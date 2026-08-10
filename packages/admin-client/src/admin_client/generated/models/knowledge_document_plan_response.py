from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.knowledge_document_plan_response_action import (
    KnowledgeDocumentPlanResponseAction,
)
from ..models.knowledge_document_plan_response_status import (
    KnowledgeDocumentPlanResponseStatus,
)

T = TypeVar("T", bound="KnowledgeDocumentPlanResponse")


@_attrs_define
class KnowledgeDocumentPlanResponse:
    """
    Attributes:
        action (KnowledgeDocumentPlanResponseAction):
        current_revision_number (int | None):
        key (str):
        status (KnowledgeDocumentPlanResponseStatus):
    """

    action: KnowledgeDocumentPlanResponseAction
    current_revision_number: int | None
    key: str
    status: KnowledgeDocumentPlanResponseStatus
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        action = self.action.value

        current_revision_number: int | None
        current_revision_number = self.current_revision_number

        key = self.key

        status = self.status.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "action": action,
                "current_revision_number": current_revision_number,
                "key": key,
                "status": status,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        action = KnowledgeDocumentPlanResponseAction(d.pop("action"))

        def _parse_current_revision_number(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        current_revision_number = _parse_current_revision_number(
            d.pop("current_revision_number")
        )

        key = d.pop("key")

        status = KnowledgeDocumentPlanResponseStatus(d.pop("status"))

        knowledge_document_plan_response = cls(
            action=action,
            current_revision_number=current_revision_number,
            key=key,
            status=status,
        )

        knowledge_document_plan_response.additional_properties = d
        return knowledge_document_plan_response

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
