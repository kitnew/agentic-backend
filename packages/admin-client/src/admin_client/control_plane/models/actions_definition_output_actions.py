from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.post_call_action_definition_output import (
        PostCallActionDefinitionOutput,
    )
    from ..models.runtime_action_definition_output import RuntimeActionDefinitionOutput


T = TypeVar("T", bound="ActionsDefinitionOutputActions")


@_attrs_define
class ActionsDefinitionOutputActions:
    """ """

    additional_properties: dict[
        str, PostCallActionDefinitionOutput | RuntimeActionDefinitionOutput
    ] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.runtime_action_definition_output import (
            RuntimeActionDefinitionOutput,
        )

        field_dict: dict[str, Any] = {}
        for prop_name, prop in self.additional_properties.items():
            if isinstance(prop, RuntimeActionDefinitionOutput):
                field_dict[prop_name] = prop.to_dict()
            else:
                field_dict[prop_name] = prop.to_dict()

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.post_call_action_definition_output import (
            PostCallActionDefinitionOutput,
        )
        from ..models.runtime_action_definition_output import (
            RuntimeActionDefinitionOutput,
        )

        d = dict(src_dict)
        actions_definition_output_actions = cls()

        additional_properties = {}
        for prop_name, prop_dict in d.items():

            def _parse_additional_property(
                data: object,
            ) -> PostCallActionDefinitionOutput | RuntimeActionDefinitionOutput:
                try:
                    if not isinstance(data, dict):
                        raise TypeError()
                    additional_property_type_0 = (
                        RuntimeActionDefinitionOutput.from_dict(data)
                    )

                    return additional_property_type_0
                except (TypeError, ValueError, AttributeError, KeyError):
                    pass
                if not isinstance(data, dict):
                    raise TypeError()
                additional_property_type_1 = PostCallActionDefinitionOutput.from_dict(
                    data
                )

                return additional_property_type_1

            additional_property = _parse_additional_property(prop_dict)

            additional_properties[prop_name] = additional_property

        actions_definition_output_actions.additional_properties = additional_properties
        return actions_definition_output_actions

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(
        self, key: str
    ) -> PostCallActionDefinitionOutput | RuntimeActionDefinitionOutput:
        return self.additional_properties[key]

    def __setitem__(
        self,
        key: str,
        value: PostCallActionDefinitionOutput | RuntimeActionDefinitionOutput,
    ) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
