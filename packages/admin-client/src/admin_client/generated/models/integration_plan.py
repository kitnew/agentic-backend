from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.integration_plan_credential import IntegrationPlanCredential
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.integration_issue import IntegrationIssue
    from ..models.integration_plan_change import IntegrationPlanChange


T = TypeVar("T", bound="IntegrationPlan")


@_attrs_define
class IntegrationPlan:
    """
    Attributes:
        credential (IntegrationPlanCredential):
        valid (bool):
        would_be_ready (bool):
        changes (list[IntegrationPlanChange] | Unset):
        issues (list[IntegrationIssue] | Unset):
        live_apply (bool | Unset):  Default: True.
    """

    credential: IntegrationPlanCredential
    valid: bool
    would_be_ready: bool
    changes: list[IntegrationPlanChange] | Unset = UNSET
    issues: list[IntegrationIssue] | Unset = UNSET
    live_apply: bool | Unset = True
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        credential = self.credential.value

        valid = self.valid

        would_be_ready = self.would_be_ready

        changes: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.changes, Unset):
            changes = []
            for changes_item_data in self.changes:
                changes_item = changes_item_data.to_dict()
                changes.append(changes_item)

        issues: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.issues, Unset):
            issues = []
            for issues_item_data in self.issues:
                issues_item = issues_item_data.to_dict()
                issues.append(issues_item)

        live_apply = self.live_apply

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "credential": credential,
                "valid": valid,
                "would_be_ready": would_be_ready,
            }
        )
        if changes is not UNSET:
            field_dict["changes"] = changes
        if issues is not UNSET:
            field_dict["issues"] = issues
        if live_apply is not UNSET:
            field_dict["live_apply"] = live_apply

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.integration_issue import IntegrationIssue
        from ..models.integration_plan_change import IntegrationPlanChange

        d = dict(src_dict)
        credential = IntegrationPlanCredential(d.pop("credential"))

        valid = d.pop("valid")

        would_be_ready = d.pop("would_be_ready")

        _changes = d.pop("changes", UNSET)
        changes: list[IntegrationPlanChange] | Unset = UNSET
        if _changes is not UNSET:
            changes = []
            for changes_item_data in _changes:
                changes_item = IntegrationPlanChange.from_dict(changes_item_data)

                changes.append(changes_item)

        _issues = d.pop("issues", UNSET)
        issues: list[IntegrationIssue] | Unset = UNSET
        if _issues is not UNSET:
            issues = []
            for issues_item_data in _issues:
                issues_item = IntegrationIssue.from_dict(issues_item_data)

                issues.append(issues_item)

        live_apply = d.pop("live_apply", UNSET)

        integration_plan = cls(
            credential=credential,
            valid=valid,
            would_be_ready=would_be_ready,
            changes=changes,
            issues=issues,
            live_apply=live_apply,
        )

        integration_plan.additional_properties = d
        return integration_plan

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
