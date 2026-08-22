from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.component_draft_response_payload import ComponentDraftResponsePayload


T = TypeVar("T", bound="ComponentDraftResponse")


@_attrs_define
class ComponentDraftResponse:
    """
    Attributes:
        comment (None | str):
        component (str):
        id (UUID):
        payload (ComponentDraftResponsePayload):
        updated_at (datetime.datetime):
        version (int):
    """

    comment: None | str
    component: str
    id: UUID
    payload: ComponentDraftResponsePayload
    updated_at: datetime.datetime
    version: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        comment: None | str
        comment = self.comment

        component = self.component

        id = str(self.id)

        payload = self.payload.to_dict()

        updated_at = self.updated_at.isoformat()

        version = self.version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "comment": comment,
                "component": component,
                "id": id,
                "payload": payload,
                "updated_at": updated_at,
                "version": version,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.component_draft_response_payload import (
            ComponentDraftResponsePayload,
        )

        d = dict(src_dict)

        def _parse_comment(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        comment = _parse_comment(d.pop("comment"))

        component = d.pop("component")

        id = UUID(d.pop("id"))

        payload = ComponentDraftResponsePayload.from_dict(d.pop("payload"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        version = d.pop("version")

        component_draft_response = cls(
            comment=comment,
            component=component,
            id=id,
            payload=payload,
            updated_at=updated_at,
            version=version,
        )

        component_draft_response.additional_properties = d
        return component_draft_response

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
