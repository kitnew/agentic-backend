from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.component_definition_response_metadata import (
        ComponentDefinitionResponseMetadata,
    )
    from ..models.component_definition_response_value_schema import (
        ComponentDefinitionResponseValueSchema,
    )


T = TypeVar("T", bound="ComponentDefinitionResponse")


@_attrs_define
class ComponentDefinitionResponse:
    """
    Attributes:
        allowed_scopes (list[str]):
        key (str):
        metadata (ComponentDefinitionResponseMetadata):
        schema_version (int):
        value_schema (ComponentDefinitionResponseValueSchema):
    """

    allowed_scopes: list[str]
    key: str
    metadata: ComponentDefinitionResponseMetadata
    schema_version: int
    value_schema: ComponentDefinitionResponseValueSchema

    def to_dict(self) -> dict[str, Any]:
        allowed_scopes = self.allowed_scopes

        key = self.key

        metadata = self.metadata.to_dict()

        schema_version = self.schema_version

        value_schema = self.value_schema.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "allowed_scopes": allowed_scopes,
                "key": key,
                "metadata": metadata,
                "schema_version": schema_version,
                "value_schema": value_schema,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.component_definition_response_metadata import (
            ComponentDefinitionResponseMetadata,
        )
        from ..models.component_definition_response_value_schema import (
            ComponentDefinitionResponseValueSchema,
        )

        d = dict(src_dict)
        allowed_scopes = cast(list[str], d.pop("allowed_scopes"))

        key = d.pop("key")

        metadata = ComponentDefinitionResponseMetadata.from_dict(d.pop("metadata"))

        schema_version = d.pop("schema_version")

        value_schema = ComponentDefinitionResponseValueSchema.from_dict(
            d.pop("value_schema")
        )

        component_definition_response = cls(
            allowed_scopes=allowed_scopes,
            key=key,
            metadata=metadata,
            schema_version=schema_version,
            value_schema=value_schema,
        )

        return component_definition_response
