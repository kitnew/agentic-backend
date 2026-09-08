from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.tenant_configuration_changes import TenantConfigurationChanges
    from ..models.validation_issue import ValidationIssue


T = TypeVar("T", bound="TenantConfigurationPlan")


@_attrs_define
class TenantConfigurationPlan:
    """
    Attributes:
        changes (TenantConfigurationChanges):
        errors (list[ValidationIssue]):
        valid (bool):
        warnings (list[str]):
    """

    changes: TenantConfigurationChanges
    errors: list[ValidationIssue]
    valid: bool
    warnings: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        changes = self.changes.to_dict()

        errors = []
        for errors_item_data in self.errors:
            errors_item = errors_item_data.to_dict()
            errors.append(errors_item)

        valid = self.valid

        warnings = self.warnings

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "changes": changes,
                "errors": errors,
                "valid": valid,
                "warnings": warnings,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.tenant_configuration_changes import TenantConfigurationChanges
        from ..models.validation_issue import ValidationIssue

        d = dict(src_dict)
        changes = TenantConfigurationChanges.from_dict(d.pop("changes"))

        errors = []
        _errors = d.pop("errors")
        for errors_item_data in _errors:
            errors_item = ValidationIssue.from_dict(errors_item_data)

            errors.append(errors_item)

        valid = d.pop("valid")

        warnings = cast(list[str], d.pop("warnings"))

        tenant_configuration_plan = cls(
            changes=changes,
            errors=errors,
            valid=valid,
            warnings=warnings,
        )

        tenant_configuration_plan.additional_properties = d
        return tenant_configuration_plan

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
