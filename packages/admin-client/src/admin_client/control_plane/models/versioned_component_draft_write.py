from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.versioned_component_draft_write_value import (
        VersionedComponentDraftWriteValue,
    )


T = TypeVar("T", bound="VersionedComponentDraftWrite")


@_attrs_define
class VersionedComponentDraftWrite:
    """
    Attributes:
        value (VersionedComponentDraftWriteValue):
    """

    value: VersionedComponentDraftWriteValue

    def to_dict(self) -> dict[str, Any]:
        value = self.value.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "value": value,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.versioned_component_draft_write_value import (
            VersionedComponentDraftWriteValue,
        )

        d = dict(src_dict)
        value = VersionedComponentDraftWriteValue.from_dict(d.pop("value"))

        versioned_component_draft_write = cls(
            value=value,
        )

        return versioned_component_draft_write
