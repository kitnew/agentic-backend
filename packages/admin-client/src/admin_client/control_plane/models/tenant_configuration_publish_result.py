from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.tenant_configuration import TenantConfiguration


T = TypeVar("T", bound="TenantConfigurationPublishResult")


@_attrs_define
class TenantConfigurationPublishResult:
    """
    Attributes:
        configuration (TenantConfiguration):
        published_components (list[str]):
        unchanged_components (list[str]):
    """

    configuration: TenantConfiguration
    published_components: list[str]
    unchanged_components: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        configuration = self.configuration.to_dict()

        published_components = self.published_components

        unchanged_components = self.unchanged_components

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "configuration": configuration,
                "published_components": published_components,
                "unchanged_components": unchanged_components,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.tenant_configuration import TenantConfiguration

        d = dict(src_dict)
        configuration = TenantConfiguration.from_dict(d.pop("configuration"))

        published_components = cast(list[str], d.pop("published_components"))

        unchanged_components = cast(list[str], d.pop("unchanged_components"))

        tenant_configuration_publish_result = cls(
            configuration=configuration,
            published_components=published_components,
            unchanged_components=unchanged_components,
        )

        tenant_configuration_publish_result.additional_properties = d
        return tenant_configuration_publish_result

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
