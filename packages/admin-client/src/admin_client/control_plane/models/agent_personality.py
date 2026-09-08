from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="AgentPersonality")


@_attrs_define
class AgentPersonality:
    """
    Attributes:
        conversation_scope (Literal['property_only']):
        display_name (str):
        greeting (str):
        identity (str):
    """

    conversation_scope: Literal["property_only"]
    display_name: str
    greeting: str
    identity: str

    def to_dict(self) -> dict[str, Any]:
        conversation_scope = self.conversation_scope

        display_name = self.display_name

        greeting = self.greeting

        identity = self.identity

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "conversation_scope": conversation_scope,
                "display_name": display_name,
                "greeting": greeting,
                "identity": identity,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        conversation_scope = cast(Literal["property_only"], d.pop("conversation_scope"))
        if conversation_scope != "property_only":
            raise ValueError(
                f"conversation_scope must match const 'property_only', got '{conversation_scope}'"
            )

        display_name = d.pop("display_name")

        greeting = d.pop("greeting")

        identity = d.pop("identity")

        agent_personality = cls(
            conversation_scope=conversation_scope,
            display_name=display_name,
            greeting=greeting,
            identity=identity,
        )

        return agent_personality
