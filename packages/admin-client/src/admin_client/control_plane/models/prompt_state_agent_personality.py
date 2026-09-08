from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.agent_personality import AgentPersonality


T = TypeVar("T", bound="PromptStateAgentPersonality")


@_attrs_define
class PromptStateAgentPersonality:
    """
    Attributes:
        active (AgentPersonality | None | Unset):
        draft (AgentPersonality | None | Unset):
    """

    active: AgentPersonality | None | Unset = UNSET
    draft: AgentPersonality | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.agent_personality import AgentPersonality

        active: dict[str, Any] | None | Unset
        if isinstance(self.active, Unset):
            active = UNSET
        elif isinstance(self.active, AgentPersonality):
            active = self.active.to_dict()
        else:
            active = self.active

        draft: dict[str, Any] | None | Unset
        if isinstance(self.draft, Unset):
            draft = UNSET
        elif isinstance(self.draft, AgentPersonality):
            draft = self.draft.to_dict()
        else:
            draft = self.draft

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if active is not UNSET:
            field_dict["active"] = active
        if draft is not UNSET:
            field_dict["draft"] = draft

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.agent_personality import AgentPersonality

        d = dict(src_dict)

        def _parse_active(data: object) -> AgentPersonality | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                active_type_0 = AgentPersonality.from_dict(data)

                return active_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AgentPersonality | None | Unset, data)

        active = _parse_active(d.pop("active", UNSET))

        def _parse_draft(data: object) -> AgentPersonality | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                draft_type_0 = AgentPersonality.from_dict(data)

                return draft_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AgentPersonality | None | Unset, data)

        draft = _parse_draft(d.pop("draft", UNSET))

        prompt_state_agent_personality = cls(
            active=active,
            draft=draft,
        )

        return prompt_state_agent_personality
