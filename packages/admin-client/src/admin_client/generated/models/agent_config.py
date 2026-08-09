from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="AgentConfig")


@_attrs_define
class AgentConfig:
    """
    Attributes:
        display_name (str):
        greeting (str):
    """

    display_name: str
    greeting: str

    def to_dict(self) -> dict[str, Any]:
        display_name = self.display_name

        greeting = self.greeting

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "display_name": display_name,
                "greeting": greeting,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        display_name = d.pop("display_name")

        greeting = d.pop("greeting")

        agent_config = cls(
            display_name=display_name,
            greeting=greeting,
        )

        return agent_config
