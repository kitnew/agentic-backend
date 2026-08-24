from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.expression_node import ExpressionNode
    from ..models.mapping_template_type_2 import MappingTemplateType2


T = TypeVar("T", bound="HttpOperationQueryType0")


@_attrs_define
class HttpOperationQueryType0:
    """ """

    additional_properties: dict[
        str,
        bool
        | ExpressionNode
        | float
        | int
        | list[Any]
        | MappingTemplateType2
        | None
        | str,
    ] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.expression_node import ExpressionNode
        from ..models.mapping_template_type_2 import MappingTemplateType2

        field_dict: dict[str, Any] = {}
        for prop_name, prop in self.additional_properties.items():
            if isinstance(prop, ExpressionNode) or isinstance(
                prop, MappingTemplateType2
            ):
                field_dict[prop_name] = prop.to_dict()
            elif isinstance(prop, list):
                field_dict[prop_name] = prop

            else:
                field_dict[prop_name] = prop

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.expression_node import ExpressionNode
        from ..models.mapping_template_type_2 import MappingTemplateType2

        d = dict(src_dict)
        http_operation_query_type_0 = cls()

        additional_properties = {}
        for prop_name, prop_dict in d.items():

            def _parse_additional_property(
                data: object,
            ) -> (
                bool
                | ExpressionNode
                | float
                | int
                | list[Any]
                | MappingTemplateType2
                | None
                | str
            ):
                if data is None:
                    return data
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    componentsschemas_mapping_template_type_1 = (
                        ExpressionNode.from_dict(data)
                    )

                    return componentsschemas_mapping_template_type_1
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    componentsschemas_mapping_template_type_2 = (
                        MappingTemplateType2.from_dict(data)
                    )

                    return componentsschemas_mapping_template_type_2
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                try:
                    if not isinstance(data, list):
                        raise TypeError()
                    componentsschemas_mapping_template_type_3 = cast(list[Any], data)

                    return componentsschemas_mapping_template_type_3
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                return cast(
                    bool
                    | ExpressionNode
                    | float
                    | int
                    | list[Any]
                    | MappingTemplateType2
                    | None
                    | str,
                    data,
                )

            additional_property = _parse_additional_property(prop_dict)

            additional_properties[prop_name] = additional_property

        http_operation_query_type_0.additional_properties = additional_properties
        return http_operation_query_type_0

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(
        self, key: str
    ) -> (
        bool
        | ExpressionNode
        | float
        | int
        | list[Any]
        | MappingTemplateType2
        | None
        | str
    ):
        return self.additional_properties[key]

    def __setitem__(
        self,
        key: str,
        value: bool
        | ExpressionNode
        | float
        | list[Any]
        | MappingTemplateType2
        | None
        | str,
    ) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
