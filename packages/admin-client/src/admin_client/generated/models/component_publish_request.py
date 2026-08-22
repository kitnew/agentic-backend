from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="ComponentPublishRequest")


@_attrs_define
class ComponentPublishRequest:
    """
    Attributes:
        draft_id (UUID):
        version (int):
        comment (None | str | Unset):
    """

    draft_id: UUID
    version: int
    comment: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        draft_id = str(self.draft_id)

        version = self.version

        comment: None | str | Unset
        if isinstance(self.comment, Unset):
            comment = UNSET
        else:
            comment = self.comment

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "draft_id": draft_id,
                "version": version,
            }
        )
        if comment is not UNSET:
            field_dict["comment"] = comment

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        draft_id = UUID(d.pop("draft_id"))

        version = d.pop("version")

        def _parse_comment(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        comment = _parse_comment(d.pop("comment", UNSET))

        component_publish_request = cls(
            draft_id=draft_id,
            version=version,
            comment=comment,
        )

        return component_publish_request
