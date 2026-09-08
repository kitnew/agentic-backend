from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.http_request_spec_input_codec import HttpRequestSpecInputCodec
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.mapping_template_input import MappingTemplateInput


T = TypeVar("T", bound="HttpRequestSpecInput")


@_attrs_define
class HttpRequestSpecInput:
    """
    Attributes:
        codec (HttpRequestSpecInputCodec):
        content_type (None | str | Unset):
        mapping (MappingTemplateInput | Unset):
    """

    codec: HttpRequestSpecInputCodec
    content_type: None | str | Unset = UNSET
    mapping: MappingTemplateInput | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        codec = self.codec.value

        content_type: None | str | Unset
        if isinstance(self.content_type, Unset):
            content_type = UNSET
        else:
            content_type = self.content_type

        mapping: dict[str, Any] | Unset = UNSET
        if not isinstance(self.mapping, Unset):
            mapping = self.mapping.to_dict()

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
        from ..models.mapping_template_input import MappingTemplateInput

        d = dict(src_dict)
        codec = HttpRequestSpecInputCodec(d.pop("codec"))

        def _parse_content_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        content_type = _parse_content_type(d.pop("content_type", UNSET))

        _mapping = d.pop("mapping", UNSET)
        mapping: MappingTemplateInput | Unset
        if isinstance(_mapping, Unset):
            mapping = UNSET
        else:
            mapping = MappingTemplateInput.from_dict(_mapping)

        http_request_spec_input = cls(
            codec=codec,
            content_type=content_type,
            mapping=mapping,
        )

        return http_request_spec_input
