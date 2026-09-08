from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.actions_availability_actions import ActionsAvailabilityActions


T = TypeVar("T", bound="ActionsAvailability")


@_attrs_define
class ActionsAvailability:
    """
    Attributes:
        actions (ActionsAvailabilityActions):
    """

    actions: ActionsAvailabilityActions

    def to_dict(self) -> dict[str, Any]:
        actions = self.actions.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "actions": actions,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.actions_availability_actions import ActionsAvailabilityActions

        d = dict(src_dict)
        actions = ActionsAvailabilityActions.from_dict(d.pop("actions"))

        actions_availability = cls(
            actions=actions,
        )

        return actions_availability
