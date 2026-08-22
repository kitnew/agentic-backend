from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.component_draft_write_payload import ComponentDraftWritePayload


T = TypeVar("T", bound="ComponentDraftWrite")


@_attrs_define
class ComponentDraftWrite:
    """
    Attributes:
        payload (ComponentDraftWritePayload):
        comment (None | str | Unset):
    """

    payload: ComponentDraftWritePayload
    comment: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        payload = self.payload.to_dict()

        comment: None | str | Unset
        if isinstance(self.comment, Unset):
            comment = UNSET
        else:
            comment = self.comment

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "payload": payload,
            }
        )
        if comment is not UNSET:
            field_dict["comment"] = comment

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.component_draft_write_payload import ComponentDraftWritePayload

        d = dict(src_dict)
        payload = ComponentDraftWritePayload.from_dict(d.pop("payload"))

        def _parse_comment(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        comment = _parse_comment(d.pop("comment", UNSET))

        component_draft_write = cls(
            payload=payload,
            comment=comment,
        )

        return component_draft_write
