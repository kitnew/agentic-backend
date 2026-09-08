from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.actions_availability import ActionsAvailability
    from ..models.architecture import Architecture
    from ..models.profile_reference import ProfileReference
    from ..models.runtime_overrides import RuntimeOverrides


T = TypeVar("T", bound="TenantLiveConfiguration")


@_attrs_define
class TenantLiveConfiguration:
    """
    Attributes:
        actions_availability (ActionsAvailability):
        architecture (Architecture):
        profile_reference (ProfileReference):
        runtime_overrides (RuntimeOverrides):
    """

    actions_availability: ActionsAvailability
    architecture: Architecture
    profile_reference: ProfileReference
    runtime_overrides: RuntimeOverrides

    def to_dict(self) -> dict[str, Any]:
        actions_availability = self.actions_availability.to_dict()

        architecture = self.architecture.to_dict()

        profile_reference = self.profile_reference.to_dict()

        runtime_overrides = self.runtime_overrides.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "actions_availability": actions_availability,
                "architecture": architecture,
                "profile_reference": profile_reference,
                "runtime_overrides": runtime_overrides,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.actions_availability import ActionsAvailability
        from ..models.architecture import Architecture
        from ..models.profile_reference import ProfileReference
        from ..models.runtime_overrides import RuntimeOverrides

        d = dict(src_dict)
        actions_availability = ActionsAvailability.from_dict(
            d.pop("actions_availability")
        )

        architecture = Architecture.from_dict(d.pop("architecture"))

        profile_reference = ProfileReference.from_dict(d.pop("profile_reference"))

        runtime_overrides = RuntimeOverrides.from_dict(d.pop("runtime_overrides"))

        tenant_live_configuration = cls(
            actions_availability=actions_availability,
            architecture=architecture,
            profile_reference=profile_reference,
            runtime_overrides=runtime_overrides,
        )

        return tenant_live_configuration
