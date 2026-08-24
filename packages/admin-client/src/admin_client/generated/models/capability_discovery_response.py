from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.capability_semantic_descriptor import CapabilitySemanticDescriptor
    from ..models.catalog_descriptor import CatalogDescriptor


T = TypeVar("T", bound="CapabilityDiscoveryResponse")


@_attrs_define
class CapabilityDiscoveryResponse:
    """
    Attributes:
        domain_fields (list[CatalogDescriptor]):
        mapping_context (list[CatalogDescriptor]):
        semantics (list[CapabilitySemanticDescriptor]):
    """

    domain_fields: list[CatalogDescriptor]
    mapping_context: list[CatalogDescriptor]
    semantics: list[CapabilitySemanticDescriptor]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        domain_fields = []
        for domain_fields_item_data in self.domain_fields:
            domain_fields_item = domain_fields_item_data.to_dict()
            domain_fields.append(domain_fields_item)

        mapping_context = []
        for mapping_context_item_data in self.mapping_context:
            mapping_context_item = mapping_context_item_data.to_dict()
            mapping_context.append(mapping_context_item)

        semantics = []
        for semantics_item_data in self.semantics:
            semantics_item = semantics_item_data.to_dict()
            semantics.append(semantics_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "domain_fields": domain_fields,
                "mapping_context": mapping_context,
                "semantics": semantics,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.capability_semantic_descriptor import CapabilitySemanticDescriptor
        from ..models.catalog_descriptor import CatalogDescriptor

        d = dict(src_dict)
        domain_fields = []
        _domain_fields = d.pop("domain_fields")
        for domain_fields_item_data in _domain_fields:
            domain_fields_item = CatalogDescriptor.from_dict(domain_fields_item_data)

            domain_fields.append(domain_fields_item)

        mapping_context = []
        _mapping_context = d.pop("mapping_context")
        for mapping_context_item_data in _mapping_context:
            mapping_context_item = CatalogDescriptor.from_dict(
                mapping_context_item_data
            )

            mapping_context.append(mapping_context_item)

        semantics = []
        _semantics = d.pop("semantics")
        for semantics_item_data in _semantics:
            semantics_item = CapabilitySemanticDescriptor.from_dict(semantics_item_data)

            semantics.append(semantics_item)

        capability_discovery_response = cls(
            domain_fields=domain_fields,
            mapping_context=mapping_context,
            semantics=semantics,
        )

        capability_discovery_response.additional_properties = d
        return capability_discovery_response

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
