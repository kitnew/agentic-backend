from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.tenant_capability_profile import TenantCapabilityProfile


T = TypeVar("T", bound="TenantConfigV2Capabilities")


@_attrs_define
class TenantConfigV2Capabilities:
    """ """

    additional_properties: dict[str, bool | TenantCapabilityProfile] = _attrs_field(
        init=False, factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        from ..models.tenant_capability_profile import TenantCapabilityProfile

        field_dict: dict[str, Any] = {}
        for prop_name, prop in self.additional_properties.items():
            if isinstance(prop, TenantCapabilityProfile):
                field_dict[prop_name] = prop.to_dict()
            else:
                field_dict[prop_name] = prop

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.tenant_capability_profile import TenantCapabilityProfile

        d = dict(src_dict)
        tenant_config_v2_capabilities = cls()

        additional_properties = {}
        for prop_name, prop_dict in d.items():

            def _parse_additional_property(
                data: object,
            ) -> bool | TenantCapabilityProfile:
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    additional_property_type_1 = TenantCapabilityProfile.from_dict(data)

                    return additional_property_type_1
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                return cast(bool | TenantCapabilityProfile, data)

            additional_property = _parse_additional_property(prop_dict)

            additional_properties[prop_name] = additional_property

        tenant_config_v2_capabilities.additional_properties = additional_properties
        return tenant_config_v2_capabilities

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> bool | TenantCapabilityProfile:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: bool | TenantCapabilityProfile) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
