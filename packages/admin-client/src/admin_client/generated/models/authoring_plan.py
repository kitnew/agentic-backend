from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.authoring_change import AuthoringChange
    from ..models.authoring_impact import AuthoringImpact
    from ..models.authoring_issue import AuthoringIssue


T = TypeVar("T", bound="AuthoringPlan")


@_attrs_define
class AuthoringPlan:
    """
    Attributes:
        valid (bool):
        changes (list[AuthoringChange] | Unset):
        errors (list[AuthoringIssue] | Unset):
        impact (AuthoringImpact | Unset):
        warnings (list[AuthoringIssue] | Unset):
    """

    valid: bool
    changes: list[AuthoringChange] | Unset = UNSET
    errors: list[AuthoringIssue] | Unset = UNSET
    impact: AuthoringImpact | Unset = UNSET
    warnings: list[AuthoringIssue] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        valid = self.valid

        changes: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.changes, Unset):
            changes = []
            for changes_item_data in self.changes:
                changes_item = changes_item_data.to_dict()
                changes.append(changes_item)

        errors: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.errors, Unset):
            errors = []
            for errors_item_data in self.errors:
                errors_item = errors_item_data.to_dict()
                errors.append(errors_item)

        impact: dict[str, Any] | Unset = UNSET
        if not isinstance(self.impact, Unset):
            impact = self.impact.to_dict()

        warnings: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.warnings, Unset):
            warnings = []
            for warnings_item_data in self.warnings:
                warnings_item = warnings_item_data.to_dict()
                warnings.append(warnings_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "valid": valid,
            }
        )
        if changes is not UNSET:
            field_dict["changes"] = changes
        if errors is not UNSET:
            field_dict["errors"] = errors
        if impact is not UNSET:
            field_dict["impact"] = impact
        if warnings is not UNSET:
            field_dict["warnings"] = warnings

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.authoring_change import AuthoringChange
        from ..models.authoring_impact import AuthoringImpact
        from ..models.authoring_issue import AuthoringIssue

        d = dict(src_dict)
        valid = d.pop("valid")

        _changes = d.pop("changes", UNSET)
        changes: list[AuthoringChange] | Unset = UNSET
        if _changes is not UNSET:
            changes = []
            for changes_item_data in _changes:
                changes_item = AuthoringChange.from_dict(changes_item_data)

                changes.append(changes_item)

        _errors = d.pop("errors", UNSET)
        errors: list[AuthoringIssue] | Unset = UNSET
        if _errors is not UNSET:
            errors = []
            for errors_item_data in _errors:
                errors_item = AuthoringIssue.from_dict(errors_item_data)

                errors.append(errors_item)

        _impact = d.pop("impact", UNSET)
        impact: AuthoringImpact | Unset
        if isinstance(_impact, Unset):
            impact = UNSET
        else:
            impact = AuthoringImpact.from_dict(_impact)

        _warnings = d.pop("warnings", UNSET)
        warnings: list[AuthoringIssue] | Unset = UNSET
        if _warnings is not UNSET:
            warnings = []
            for warnings_item_data in _warnings:
                warnings_item = AuthoringIssue.from_dict(warnings_item_data)

                warnings.append(warnings_item)

        authoring_plan = cls(
            valid=valid,
            changes=changes,
            errors=errors,
            impact=impact,
            warnings=warnings,
        )

        return authoring_plan
