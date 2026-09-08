from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.live_component_write_value import LiveComponentWriteValue


T = TypeVar("T", bound="LiveComponentWrite")


@_attrs_define
class LiveComponentWrite:
    """
    Attributes:
        value (LiveComponentWriteValue):
    """

    value: LiveComponentWriteValue

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
        from ..models.live_component_write_value import LiveComponentWriteValue

        d = dict(src_dict)
        value = LiveComponentWriteValue.from_dict(d.pop("value"))

        live_component_write = cls(
            value=value,
        )

        return live_component_write
