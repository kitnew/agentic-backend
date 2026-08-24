from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.tenant_post_call_action_authoring import TenantPostCallActionAuthoring


T = TypeVar("T", bound="TenantPostCallAuthoring")


@_attrs_define
class TenantPostCallAuthoring:
    """
    Attributes:
        actions (list[TenantPostCallActionAuthoring] | Unset):
    """

    actions: list[TenantPostCallActionAuthoring] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        actions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.actions, Unset):
            actions = []
            for actions_item_data in self.actions:
                actions_item = actions_item_data.to_dict()
                actions.append(actions_item)

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if actions is not UNSET:
            field_dict["actions"] = actions

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.tenant_post_call_action_authoring import (
            TenantPostCallActionAuthoring,
        )

        d = dict(src_dict)
        _actions = d.pop("actions", UNSET)
        actions: list[TenantPostCallActionAuthoring] | Unset = UNSET
        if _actions is not UNSET:
            actions = []
            for actions_item_data in _actions:
                actions_item = TenantPostCallActionAuthoring.from_dict(
                    actions_item_data
                )

                actions.append(actions_item)

        tenant_post_call_authoring = cls(
            actions=actions,
        )

        return tenant_post_call_authoring
