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

from ..models.agent_identity_grammatical_gender import AgentIdentityGrammaticalGender
from ..types import UNSET, Unset

T = TypeVar("T", bound="AgentIdentity")


@_attrs_define
class AgentIdentity:
    """
    Attributes:
        conversation_scope (Literal['property_only']):
        display_name (str):
        greeting (str):
        role (str):
        grammatical_gender (AgentIdentityGrammaticalGender | Unset):
    """

    conversation_scope: Literal["property_only"]
    display_name: str
    greeting: str
    role: str
    grammatical_gender: AgentIdentityGrammaticalGender | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        conversation_scope = self.conversation_scope

        display_name = self.display_name

        greeting = self.greeting

        role = self.role

        grammatical_gender: str | Unset = UNSET
        if not isinstance(self.grammatical_gender, Unset):
            grammatical_gender = self.grammatical_gender.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "conversation_scope": conversation_scope,
                "display_name": display_name,
                "greeting": greeting,
                "role": role,
            }
        )
        if grammatical_gender is not UNSET:
            field_dict["grammatical_gender"] = grammatical_gender

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

        role = d.pop("role")

        _grammatical_gender = d.pop("grammatical_gender", UNSET)
        grammatical_gender: AgentIdentityGrammaticalGender | Unset
        if isinstance(_grammatical_gender, Unset):
            grammatical_gender = UNSET
        else:
            grammatical_gender = AgentIdentityGrammaticalGender(_grammatical_gender)

        agent_identity = cls(
            conversation_scope=conversation_scope,
            display_name=display_name,
            greeting=greeting,
            role=role,
            grammatical_gender=grammatical_gender,
        )

        return agent_identity
