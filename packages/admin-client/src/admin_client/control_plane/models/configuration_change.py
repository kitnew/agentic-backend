from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="ConfigurationChange")


@_attrs_define
class ConfigurationChange:
    """
    Attributes:
        operation (str):
        path (str):
        activation (str | Unset):  Default: 'immediate'.
    """

    operation: str
    path: str
    activation: str | Unset = "immediate"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        operation = self.operation

        path = self.path

        activation = self.activation

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "operation": operation,
                "path": path,
            }
        )
        if activation is not UNSET:
            field_dict["activation"] = activation

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        operation = d.pop("operation")

        path = d.pop("path")

        activation = d.pop("activation", UNSET)

        configuration_change = cls(
            operation=operation,
            path=path,
            activation=activation,
        )

        configuration_change.additional_properties = d
        return configuration_change

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
