from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="AuthoringDraftMetadata")


@_attrs_define
class AuthoringDraftMetadata:
    """
    Attributes:
        id (UUID):
        updated_at (datetime.datetime):
        version (int):
        comment (None | str | Unset):
    """

    id: UUID
    updated_at: datetime.datetime
    version: int
    comment: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        updated_at = self.updated_at.isoformat()

        version = self.version

        comment: None | str | Unset
        if isinstance(self.comment, Unset):
            comment = UNSET
        else:
            comment = self.comment

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "updated_at": updated_at,
                "version": version,
            }
        )
        if comment is not UNSET:
            field_dict["comment"] = comment

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        version = d.pop("version")

        def _parse_comment(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        comment = _parse_comment(d.pop("comment", UNSET))

        authoring_draft_metadata = cls(
            id=id,
            updated_at=updated_at,
            version=version,
            comment=comment,
        )

        return authoring_draft_metadata
