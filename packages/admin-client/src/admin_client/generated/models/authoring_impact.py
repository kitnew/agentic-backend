from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="AuthoringImpact")


@_attrs_define
class AuthoringImpact:
    """
    Attributes:
        affected_components (list[str] | Unset):
        new_release_required (bool | Unset):  Default: False.
        runtime_bundle_changes (bool | Unset):  Default: False.
        telephony_reconciliation_required (bool | Unset):  Default: False.
    """

    affected_components: list[str] | Unset = UNSET
    new_release_required: bool | Unset = False
    runtime_bundle_changes: bool | Unset = False
    telephony_reconciliation_required: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        affected_components: list[str] | Unset = UNSET
        if not isinstance(self.affected_components, Unset):
            affected_components = self.affected_components

        new_release_required = self.new_release_required

        runtime_bundle_changes = self.runtime_bundle_changes

        telephony_reconciliation_required = self.telephony_reconciliation_required

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if affected_components is not UNSET:
            field_dict["affected_components"] = affected_components
        if new_release_required is not UNSET:
            field_dict["new_release_required"] = new_release_required
        if runtime_bundle_changes is not UNSET:
            field_dict["runtime_bundle_changes"] = runtime_bundle_changes
        if telephony_reconciliation_required is not UNSET:
            field_dict["telephony_reconciliation_required"] = (
                telephony_reconciliation_required
            )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        affected_components = cast(list[str], d.pop("affected_components", UNSET))

        new_release_required = d.pop("new_release_required", UNSET)

        runtime_bundle_changes = d.pop("runtime_bundle_changes", UNSET)

        telephony_reconciliation_required = d.pop(
            "telephony_reconciliation_required", UNSET
        )

        authoring_impact = cls(
            affected_components=affected_components,
            new_release_required=new_release_required,
            runtime_bundle_changes=runtime_bundle_changes,
            telephony_reconciliation_required=telephony_reconciliation_required,
        )

        return authoring_impact
