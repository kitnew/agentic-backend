from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.handoff_config_destinations import HandoffConfigDestinations


T = TypeVar("T", bound="HandoffConfig")


@_attrs_define
class HandoffConfig:
    """
    Attributes:
        destinations (HandoffConfigDestinations | Unset):
    """

    destinations: HandoffConfigDestinations | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        destinations: dict[str, Any] | Unset = UNSET
        if not isinstance(self.destinations, Unset):
            destinations = self.destinations.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if destinations is not UNSET:
            field_dict["destinations"] = destinations

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.handoff_config_destinations import HandoffConfigDestinations

        d = dict(src_dict)
        _destinations = d.pop("destinations", UNSET)
        destinations: HandoffConfigDestinations | Unset
        if isinstance(_destinations, Unset):
            destinations = UNSET
        else:
            destinations = HandoffConfigDestinations.from_dict(_destinations)

        handoff_config = cls(
            destinations=destinations,
        )

        return handoff_config
