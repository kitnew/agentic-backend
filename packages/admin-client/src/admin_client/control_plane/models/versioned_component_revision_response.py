from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.versioned_component_revision_response_value import (
        VersionedComponentRevisionResponseValue,
    )


T = TypeVar("T", bound="VersionedComponentRevisionResponse")


@_attrs_define
class VersionedComponentRevisionResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        created_by (str):
        restored_from_revision (int | None):
        revision_number (int):
        schema_version (int):
        value (VersionedComponentRevisionResponseValue):
    """

    created_at: datetime.datetime
    created_by: str
    restored_from_revision: int | None
    revision_number: int
    schema_version: int
    value: VersionedComponentRevisionResponseValue

    def to_dict(self) -> dict[str, Any]:
        created_at = self.created_at.isoformat()

        created_by = self.created_by

        restored_from_revision: int | None
        restored_from_revision = self.restored_from_revision

        revision_number = self.revision_number

        schema_version = self.schema_version

        value = self.value.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "created_at": created_at,
                "created_by": created_by,
                "restored_from_revision": restored_from_revision,
                "revision_number": revision_number,
                "schema_version": schema_version,
                "value": value,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.versioned_component_revision_response_value import (
            VersionedComponentRevisionResponseValue,
        )

        d = dict(src_dict)
        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        created_by = d.pop("created_by")

        def _parse_restored_from_revision(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        restored_from_revision = _parse_restored_from_revision(
            d.pop("restored_from_revision")
        )

        revision_number = d.pop("revision_number")

        schema_version = d.pop("schema_version")

        value = VersionedComponentRevisionResponseValue.from_dict(d.pop("value"))

        versioned_component_revision_response = cls(
            created_at=created_at,
            created_by=created_by,
            restored_from_revision=restored_from_revision,
            revision_number=revision_number,
            schema_version=schema_version,
            value=value,
        )

        return versioned_component_revision_response
