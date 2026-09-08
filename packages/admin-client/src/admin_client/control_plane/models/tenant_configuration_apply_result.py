from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.tenant_configuration import TenantConfiguration


T = TypeVar("T", bound="TenantConfigurationApplyResult")


@_attrs_define
class TenantConfigurationApplyResult:
    """
    Attributes:
        configuration (TenantConfiguration):
        drafts_saved (list[str]):
        live_updated (list[str]):
        unchanged (list[str]):
    """

    configuration: TenantConfiguration
    drafts_saved: list[str]
    live_updated: list[str]
    unchanged: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        configuration = self.configuration.to_dict()

        drafts_saved = self.drafts_saved

        live_updated = self.live_updated

        unchanged = self.unchanged

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "configuration": configuration,
                "drafts_saved": drafts_saved,
                "live_updated": live_updated,
                "unchanged": unchanged,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.tenant_configuration import TenantConfiguration

        d = dict(src_dict)
        configuration = TenantConfiguration.from_dict(d.pop("configuration"))

        drafts_saved = cast(list[str], d.pop("drafts_saved"))

        live_updated = cast(list[str], d.pop("live_updated"))

        unchanged = cast(list[str], d.pop("unchanged"))

        tenant_configuration_apply_result = cls(
            configuration=configuration,
            drafts_saved=drafts_saved,
            live_updated=live_updated,
            unchanged=unchanged,
        )

        tenant_configuration_apply_result.additional_properties = d
        return tenant_configuration_apply_result

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
