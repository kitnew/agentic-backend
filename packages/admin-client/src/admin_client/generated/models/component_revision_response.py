from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.component_revision_response_payload import (
        ComponentRevisionResponsePayload,
    )


T = TypeVar("T", bound="ComponentRevisionResponse")


@_attrs_define
class ComponentRevisionResponse:
    """
    Attributes:
        comment (None | str):
        id (UUID):
        payload (ComponentRevisionResponsePayload):
        revision_number (int):
        sealed_at (datetime.datetime):
    """

    comment: None | str
    id: UUID
    payload: ComponentRevisionResponsePayload
    revision_number: int
    sealed_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        comment: None | str
        comment = self.comment

        id = str(self.id)

        payload = self.payload.to_dict()

        revision_number = self.revision_number

        sealed_at = self.sealed_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "comment": comment,
                "id": id,
                "payload": payload,
                "revision_number": revision_number,
                "sealed_at": sealed_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.component_revision_response_payload import (
            ComponentRevisionResponsePayload,
        )

        d = dict(src_dict)

        def _parse_comment(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        comment = _parse_comment(d.pop("comment"))

        id = UUID(d.pop("id"))

        payload = ComponentRevisionResponsePayload.from_dict(d.pop("payload"))

        revision_number = d.pop("revision_number")

        sealed_at = datetime.datetime.fromisoformat(d.pop("sealed_at"))

        component_revision_response = cls(
            comment=comment,
            id=id,
            payload=payload,
            revision_number=revision_number,
            sealed_at=sealed_at,
        )

        component_revision_response.additional_properties = d
        return component_revision_response

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
