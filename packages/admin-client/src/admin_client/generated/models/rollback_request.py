from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="RollbackRequest")


@_attrs_define
class RollbackRequest:
    """
    Attributes:
        target_release_id (UUID):
    """

    target_release_id: UUID

    def to_dict(self) -> dict[str, Any]:
        target_release_id = str(self.target_release_id)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "target_release_id": target_release_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        target_release_id = UUID(d.pop("target_release_id"))

        rollback_request = cls(
            target_release_id=target_release_id,
        )

        return rollback_request
