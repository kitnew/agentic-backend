from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.configuration_change import ConfigurationChange


T = TypeVar("T", bound="TenantConfigurationChanges")


@_attrs_define
class TenantConfigurationChanges:
    """
    Attributes:
        draft (list[ConfigurationChange]):
        immediate (list[ConfigurationChange]):
    """

    draft: list[ConfigurationChange]
    immediate: list[ConfigurationChange]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        draft = []
        for draft_item_data in self.draft:
            draft_item = draft_item_data.to_dict()
            draft.append(draft_item)

        immediate = []
        for immediate_item_data in self.immediate:
            immediate_item = immediate_item_data.to_dict()
            immediate.append(immediate_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "draft": draft,
                "immediate": immediate,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.configuration_change import ConfigurationChange

        d = dict(src_dict)
        draft = []
        _draft = d.pop("draft")
        for draft_item_data in _draft:
            draft_item = ConfigurationChange.from_dict(draft_item_data)

            draft.append(draft_item)

        immediate = []
        _immediate = d.pop("immediate")
        for immediate_item_data in _immediate:
            immediate_item = ConfigurationChange.from_dict(immediate_item_data)

            immediate.append(immediate_item)

        tenant_configuration_changes = cls(
            draft=draft,
            immediate=immediate,
        )

        tenant_configuration_changes.additional_properties = d
        return tenant_configuration_changes

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
