from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.knowledge_base_snapshot_response import KnowledgeBaseSnapshotResponse


T = TypeVar("T", bound="KnowledgeBasePushResponse")


@_attrs_define
class KnowledgeBasePushResponse:
    """
    Attributes:
        changed (bool):
        draft (KnowledgeBaseSnapshotResponse | None):
    """

    changed: bool
    draft: KnowledgeBaseSnapshotResponse | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.knowledge_base_snapshot_response import (
            KnowledgeBaseSnapshotResponse,
        )

        changed = self.changed

        draft: dict[str, Any] | None
        if isinstance(self.draft, KnowledgeBaseSnapshotResponse):
            draft = self.draft.to_dict()
        else:
            draft = self.draft

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "changed": changed,
                "draft": draft,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.knowledge_base_snapshot_response import (
            KnowledgeBaseSnapshotResponse,
        )

        d = dict(src_dict)
        changed = d.pop("changed")

        def _parse_draft(data: object) -> KnowledgeBaseSnapshotResponse | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                draft_type_0 = KnowledgeBaseSnapshotResponse.from_dict(data)

                return draft_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(KnowledgeBaseSnapshotResponse | None, data)

        draft = _parse_draft(d.pop("draft"))

        knowledge_base_push_response = cls(
            changed=changed,
            draft=draft,
        )

        knowledge_base_push_response.additional_properties = d
        return knowledge_base_push_response

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
