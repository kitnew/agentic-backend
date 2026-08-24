from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.http_request_spec_codec import HttpRequestSpecCodec
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.expression_node import ExpressionNode
    from ..models.mapping_template_type_2 import MappingTemplateType2


T = TypeVar("T", bound="HttpRequestSpec")


@_attrs_define
class HttpRequestSpec:
    """
    Attributes:
        codec (HttpRequestSpecCodec):
        content_type (None | str | Unset):
        mapping (bool | ExpressionNode | float | int | list[Any] | MappingTemplateType2 | None | str | Unset):
    """

    codec: HttpRequestSpecCodec
    content_type: None | str | Unset = UNSET
    mapping: (
        bool
        | ExpressionNode
        | float
        | int
        | list[Any]
        | MappingTemplateType2
        | None
        | str
        | Unset
    ) = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.expression_node import ExpressionNode
        from ..models.mapping_template_type_2 import MappingTemplateType2

        codec = self.codec.value

        content_type: None | str | Unset
        if isinstance(self.content_type, Unset):
            content_type = UNSET
        else:
            content_type = self.content_type

        mapping: bool | dict[str, Any] | float | int | list[Any] | None | str | Unset
        if isinstance(self.mapping, Unset):
            mapping = UNSET
        elif isinstance(self.mapping, ExpressionNode) or isinstance(
            self.mapping, MappingTemplateType2
        ):
            mapping = self.mapping.to_dict()
        elif isinstance(self.mapping, list):
            mapping = self.mapping

        else:
            mapping = self.mapping

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "codec": codec,
            }
        )
        if content_type is not UNSET:
            field_dict["content_type"] = content_type
        if mapping is not UNSET:
            field_dict["mapping"] = mapping

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.expression_node import ExpressionNode
        from ..models.mapping_template_type_2 import MappingTemplateType2

        d = dict(src_dict)
        codec = HttpRequestSpecCodec(d.pop("codec"))

        def _parse_content_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        content_type = _parse_content_type(d.pop("content_type", UNSET))

        def _parse_mapping(
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
            | Unset
        ):
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                componentsschemas_mapping_template_type_1 = ExpressionNode.from_dict(
                    data
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
                | str
                | Unset,
                data,
            )

        mapping = _parse_mapping(d.pop("mapping", UNSET))

        http_request_spec = cls(
            codec=codec,
            content_type=content_type,
            mapping=mapping,
        )

        return http_request_spec
