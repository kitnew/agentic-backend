from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.agent_identity import AgentIdentity


T = TypeVar("T", bound="PromptStateAgentIdentity")


@_attrs_define
class PromptStateAgentIdentity:
    """
    Attributes:
        active (AgentIdentity | None | Unset):
        draft (AgentIdentity | None | Unset):
    """

    active: AgentIdentity | None | Unset = UNSET
    draft: AgentIdentity | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.agent_identity import AgentIdentity

        active: dict[str, Any] | None | Unset
        if isinstance(self.active, Unset):
            active = UNSET
        elif isinstance(self.active, AgentIdentity):
            active = self.active.to_dict()
        else:
            active = self.active

        draft: dict[str, Any] | None | Unset
        if isinstance(self.draft, Unset):
            draft = UNSET
        elif isinstance(self.draft, AgentIdentity):
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
        from ..models.agent_identity import AgentIdentity

        d = dict(src_dict)

        def _parse_active(data: object) -> AgentIdentity | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                active_type_0 = AgentIdentity.from_dict(data)

                return active_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AgentIdentity | None | Unset, data)

        active = _parse_active(d.pop("active", UNSET))

        def _parse_draft(data: object) -> AgentIdentity | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                draft_type_0 = AgentIdentity.from_dict(data)

                return draft_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AgentIdentity | None | Unset, data)

        draft = _parse_draft(d.pop("draft", UNSET))

        prompt_state_agent_identity = cls(
            active=active,
            draft=draft,
        )

        return prompt_state_agent_identity
