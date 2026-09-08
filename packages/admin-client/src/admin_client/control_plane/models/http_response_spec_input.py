from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.http_response_spec_input_codec import HttpResponseSpecInputCodec
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.mapping_template_input import MappingTemplateInput


T = TypeVar("T", bound="HttpResponseSpecInput")


@_attrs_define
class HttpResponseSpecInput:
    """
    Attributes:
        codec (HttpResponseSpecInputCodec):
        mapping (MappingTemplateInput | Unset):
    """

    codec: HttpResponseSpecInputCodec
    mapping: MappingTemplateInput | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        codec = self.codec.value

        mapping: dict[str, Any] | Unset = UNSET
        if not isinstance(self.mapping, Unset):
            mapping = self.mapping.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "codec": codec,
            }
        )
        if mapping is not UNSET:
            field_dict["mapping"] = mapping

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.mapping_template_input import MappingTemplateInput

        d = dict(src_dict)
        codec = HttpResponseSpecInputCodec(d.pop("codec"))

        _mapping = d.pop("mapping", UNSET)
        mapping: MappingTemplateInput | Unset
        if isinstance(_mapping, Unset):
            mapping = UNSET
        else:
            mapping = MappingTemplateInput.from_dict(_mapping)

        http_response_spec_input = cls(
            codec=codec,
            mapping=mapping,
        )

        return http_response_spec_input
