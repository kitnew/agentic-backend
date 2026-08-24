from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.catalog_descriptor import CatalogDescriptor
    from ..models.post_call_artifact_descriptor import PostCallArtifactDescriptor


T = TypeVar("T", bound="PostCallDiscoveryResponse")


@_attrs_define
class PostCallDiscoveryResponse:
    """
    Attributes:
        artifacts (list[PostCallArtifactDescriptor]):
        mapping_context (list[CatalogDescriptor]):
    """

    artifacts: list[PostCallArtifactDescriptor]
    mapping_context: list[CatalogDescriptor]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        artifacts = []
        for artifacts_item_data in self.artifacts:
            artifacts_item = artifacts_item_data.to_dict()
            artifacts.append(artifacts_item)

        mapping_context = []
        for mapping_context_item_data in self.mapping_context:
            mapping_context_item = mapping_context_item_data.to_dict()
            mapping_context.append(mapping_context_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "artifacts": artifacts,
                "mapping_context": mapping_context,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.catalog_descriptor import CatalogDescriptor
        from ..models.post_call_artifact_descriptor import PostCallArtifactDescriptor

        d = dict(src_dict)
        artifacts = []
        _artifacts = d.pop("artifacts")
        for artifacts_item_data in _artifacts:
            artifacts_item = PostCallArtifactDescriptor.from_dict(artifacts_item_data)

            artifacts.append(artifacts_item)

        mapping_context = []
        _mapping_context = d.pop("mapping_context")
        for mapping_context_item_data in _mapping_context:
            mapping_context_item = CatalogDescriptor.from_dict(
                mapping_context_item_data
            )

            mapping_context.append(mapping_context_item)

        post_call_discovery_response = cls(
            artifacts=artifacts,
            mapping_context=mapping_context,
        )

        post_call_discovery_response.additional_properties = d
        return post_call_discovery_response

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
