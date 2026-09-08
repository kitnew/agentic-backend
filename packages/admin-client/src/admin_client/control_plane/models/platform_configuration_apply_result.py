from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.platform_configuration import PlatformConfiguration


T = TypeVar("T", bound="PlatformConfigurationApplyResult")


@_attrs_define
class PlatformConfigurationApplyResult:
    """
    Attributes:
        catalogs_updated (list[str]):
        configuration (PlatformConfiguration):
        drafts_saved (list[str]):
        unchanged (list[str]):
    """

    catalogs_updated: list[str]
    configuration: PlatformConfiguration
    drafts_saved: list[str]
    unchanged: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        catalogs_updated = self.catalogs_updated

        configuration = self.configuration.to_dict()

        drafts_saved = self.drafts_saved

        unchanged = self.unchanged

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "catalogs_updated": catalogs_updated,
                "configuration": configuration,
                "drafts_saved": drafts_saved,
                "unchanged": unchanged,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.platform_configuration import PlatformConfiguration

        d = dict(src_dict)
        catalogs_updated = cast(list[str], d.pop("catalogs_updated"))

        configuration = PlatformConfiguration.from_dict(d.pop("configuration"))

        drafts_saved = cast(list[str], d.pop("drafts_saved"))

        unchanged = cast(list[str], d.pop("unchanged"))

        platform_configuration_apply_result = cls(
            catalogs_updated=catalogs_updated,
            configuration=configuration,
            drafts_saved=drafts_saved,
            unchanged=unchanged,
        )

        platform_configuration_apply_result.additional_properties = d
        return platform_configuration_apply_result

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
