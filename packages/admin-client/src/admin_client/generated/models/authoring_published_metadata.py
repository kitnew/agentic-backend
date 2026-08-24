from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="AuthoringPublishedMetadata")


@_attrs_define
class AuthoringPublishedMetadata:
    """
    Attributes:
        published_at (datetime.datetime):
        revision_id (UUID):
        revision_number (int):
    """

    published_at: datetime.datetime
    revision_id: UUID
    revision_number: int

    def to_dict(self) -> dict[str, Any]:
        published_at = self.published_at.isoformat()

        revision_id = str(self.revision_id)

        revision_number = self.revision_number

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "published_at": published_at,
                "revision_id": revision_id,
                "revision_number": revision_number,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        published_at = datetime.datetime.fromisoformat(d.pop("published_at"))

        revision_id = UUID(d.pop("revision_id"))

        revision_number = d.pop("revision_number")

        authoring_published_metadata = cls(
            published_at=published_at,
            revision_id=revision_id,
            revision_number=revision_number,
        )

        return authoring_published_metadata
