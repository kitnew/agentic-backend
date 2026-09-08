from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.registry_entry_response_metadata import RegistryEntryResponseMetadata


T = TypeVar("T", bound="RegistryEntryResponse")


@_attrs_define
class RegistryEntryResponse:
    """
    Attributes:
        description (str):
        key (str):
        metadata (RegistryEntryResponseMetadata):
        name (str):
    """

    description: str
    key: str
    metadata: RegistryEntryResponseMetadata
    name: str

    def to_dict(self) -> dict[str, Any]:
        description = self.description

        key = self.key

        metadata = self.metadata.to_dict()

        name = self.name

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "description": description,
                "key": key,
                "metadata": metadata,
                "name": name,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.registry_entry_response_metadata import (
            RegistryEntryResponseMetadata,
        )

        d = dict(src_dict)
        description = d.pop("description")

        key = d.pop("key")

        metadata = RegistryEntryResponseMetadata.from_dict(d.pop("metadata"))

        name = d.pop("name")

        registry_entry_response = cls(
            description=description,
            key=key,
            metadata=metadata,
            name=name,
        )

        return registry_entry_response
