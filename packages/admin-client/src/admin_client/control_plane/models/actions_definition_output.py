from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.actions_definition_output_actions import (
        ActionsDefinitionOutputActions,
    )


T = TypeVar("T", bound="ActionsDefinitionOutput")


@_attrs_define
class ActionsDefinitionOutput:
    """
    Attributes:
        actions (ActionsDefinitionOutputActions):
    """

    actions: ActionsDefinitionOutputActions

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
        from ..models.actions_definition_output_actions import (
            ActionsDefinitionOutputActions,
        )

        d = dict(src_dict)
        actions = ActionsDefinitionOutputActions.from_dict(d.pop("actions"))

        actions_definition_output = cls(
            actions=actions,
        )

        return actions_definition_output
