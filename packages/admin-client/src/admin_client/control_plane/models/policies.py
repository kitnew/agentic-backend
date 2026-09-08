from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.cascade_policies import CascadePolicies


T = TypeVar("T", bound="Policies")


@_attrs_define
class Policies:
    """
    Attributes:
        cascade (CascadePolicies):
    """

    cascade: CascadePolicies

    def to_dict(self) -> dict[str, Any]:
        cascade = self.cascade.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "cascade": cascade,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.cascade_policies import CascadePolicies

        d = dict(src_dict)
        cascade = CascadePolicies.from_dict(d.pop("cascade"))

        policies = cls(
            cascade=cascade,
        )

        return policies
