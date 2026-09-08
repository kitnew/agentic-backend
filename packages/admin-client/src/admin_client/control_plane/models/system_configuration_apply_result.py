from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.system_configuration import SystemConfiguration


T = TypeVar("T", bound="SystemConfigurationApplyResult")


@_attrs_define
class SystemConfigurationApplyResult:
    """
    Attributes:
        configuration (SystemConfiguration):
        unchanged (list[str]):
        updated (list[str]):
    """

    configuration: SystemConfiguration
    unchanged: list[str]
    updated: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        configuration = self.configuration.to_dict()

        unchanged = self.unchanged

        updated = self.updated

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "configuration": configuration,
                "unchanged": unchanged,
                "updated": updated,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.system_configuration import SystemConfiguration

        d = dict(src_dict)
        configuration = SystemConfiguration.from_dict(d.pop("configuration"))

        unchanged = cast(list[str], d.pop("unchanged"))

        updated = cast(list[str], d.pop("updated"))

        system_configuration_apply_result = cls(
            configuration=configuration,
            unchanged=unchanged,
            updated=updated,
        )

        system_configuration_apply_result.additional_properties = d
        return system_configuration_apply_result

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
