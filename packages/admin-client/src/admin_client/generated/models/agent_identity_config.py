from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="AgentIdentityConfig")


@_attrs_define
class AgentIdentityConfig:
    """
    Attributes:
        display_name (str):
        greeting (str):
        profile (str):
    """

    display_name: str
    greeting: str
    profile: str

    def to_dict(self) -> dict[str, Any]:
        display_name = self.display_name

        greeting = self.greeting

        profile = self.profile

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "display_name": display_name,
                "greeting": greeting,
                "profile": profile,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        display_name = d.pop("display_name")

        greeting = d.pop("greeting")

        profile = d.pop("profile")

        agent_identity_config = cls(
            display_name=display_name,
            greeting=greeting,
            profile=profile,
        )

        return agent_identity_config
