from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.http_response_spec_output_codec import HttpResponseSpecOutputCodec
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.mapping_template_output import MappingTemplateOutput


T = TypeVar("T", bound="HttpResponseSpecOutput")


@_attrs_define
class HttpResponseSpecOutput:
    """
    Attributes:
        codec (HttpResponseSpecOutputCodec):
        mapping (MappingTemplateOutput | Unset):
    """

    codec: HttpResponseSpecOutputCodec
    mapping: MappingTemplateOutput | Unset = UNSET

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
        from ..models.mapping_template_output import MappingTemplateOutput

        d = dict(src_dict)
        codec = HttpResponseSpecOutputCodec(d.pop("codec"))

        _mapping = d.pop("mapping", UNSET)
        mapping: MappingTemplateOutput | Unset
        if isinstance(_mapping, Unset):
            mapping = UNSET
        else:
            mapping = MappingTemplateOutput.from_dict(_mapping)

        http_response_spec_output = cls(
            codec=codec,
            mapping=mapping,
        )

        return http_response_spec_output
