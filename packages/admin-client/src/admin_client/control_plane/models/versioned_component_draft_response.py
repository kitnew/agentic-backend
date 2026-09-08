from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.versioned_component_draft_response_value import (
        VersionedComponentDraftResponseValue,
    )


T = TypeVar("T", bound="VersionedComponentDraftResponse")


@_attrs_define
class VersionedComponentDraftResponse:
    """
    Attributes:
        based_on_revision_number (int | None):
        schema_version (int):
        updated_at (datetime.datetime):
        updated_by (str):
        value (VersionedComponentDraftResponseValue):
    """

    based_on_revision_number: int | None
    schema_version: int
    updated_at: datetime.datetime
    updated_by: str
    value: VersionedComponentDraftResponseValue

    def to_dict(self) -> dict[str, Any]:
        based_on_revision_number: int | None
        based_on_revision_number = self.based_on_revision_number

        schema_version = self.schema_version

        updated_at = self.updated_at.isoformat()

        updated_by = self.updated_by

        value = self.value.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "based_on_revision_number": based_on_revision_number,
                "schema_version": schema_version,
                "updated_at": updated_at,
                "updated_by": updated_by,
                "value": value,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.versioned_component_draft_response_value import (
            VersionedComponentDraftResponseValue,
        )

        d = dict(src_dict)

        def _parse_based_on_revision_number(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        based_on_revision_number = _parse_based_on_revision_number(
            d.pop("based_on_revision_number")
        )

        schema_version = d.pop("schema_version")

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        updated_by = d.pop("updated_by")

        value = VersionedComponentDraftResponseValue.from_dict(d.pop("value"))

        versioned_component_draft_response = cls(
            based_on_revision_number=based_on_revision_number,
            schema_version=schema_version,
            updated_at=updated_at,
            updated_by=updated_by,
            value=value,
        )

        return versioned_component_draft_response
