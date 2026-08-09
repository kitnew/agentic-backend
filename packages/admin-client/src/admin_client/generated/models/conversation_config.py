from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.conversation_scope import ConversationScope

T = TypeVar("T", bound="ConversationConfig")


@_attrs_define
class ConversationConfig:
    """
    Attributes:
        scope (ConversationScope):
    """

    scope: ConversationScope

    def to_dict(self) -> dict[str, Any]:
        scope = self.scope.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "scope": scope,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        scope = ConversationScope(d.pop("scope"))

        conversation_config = cls(
            scope=scope,
        )

        return conversation_config
