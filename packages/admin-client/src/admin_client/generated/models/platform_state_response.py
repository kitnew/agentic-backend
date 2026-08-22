from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.platform_draft_state import PlatformDraftState
    from ..models.platform_release_response import PlatformReleaseResponse
    from ..models.platform_state_response_active_profile_prompts import (
        PlatformStateResponseActiveProfilePrompts,
    )
    from ..models.platform_state_response_active_runtime_type_0 import (
        PlatformStateResponseActiveRuntimeType0,
    )
    from ..models.platform_state_response_profile_prompt_drafts import (
        PlatformStateResponseProfilePromptDrafts,
    )


T = TypeVar("T", bound="PlatformStateResponse")


@_attrs_define
class PlatformStateResponse:
    """
    Attributes:
        active_profile_prompts (PlatformStateResponseActiveProfilePrompts):
        active_release (None | PlatformReleaseResponse):
        active_runtime (None | PlatformStateResponseActiveRuntimeType0):
        active_system_prompt (None | str):
        profile_prompt_drafts (PlatformStateResponseProfilePromptDrafts):
        runtime_draft (None | PlatformDraftState):
        system_prompt_draft (None | PlatformDraftState):
    """

    active_profile_prompts: PlatformStateResponseActiveProfilePrompts
    active_release: None | PlatformReleaseResponse
    active_runtime: None | PlatformStateResponseActiveRuntimeType0
    active_system_prompt: None | str
    profile_prompt_drafts: PlatformStateResponseProfilePromptDrafts
    runtime_draft: None | PlatformDraftState
    system_prompt_draft: None | PlatformDraftState
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.platform_draft_state import PlatformDraftState
        from ..models.platform_release_response import PlatformReleaseResponse
        from ..models.platform_state_response_active_runtime_type_0 import (
            PlatformStateResponseActiveRuntimeType0,
        )

        active_profile_prompts = self.active_profile_prompts.to_dict()

        active_release: dict[str, Any] | None
        if isinstance(self.active_release, PlatformReleaseResponse):
            active_release = self.active_release.to_dict()
        else:
            active_release = self.active_release

        active_runtime: dict[str, Any] | None
        if isinstance(self.active_runtime, PlatformStateResponseActiveRuntimeType0):
            active_runtime = self.active_runtime.to_dict()
        else:
            active_runtime = self.active_runtime

        active_system_prompt: None | str
        active_system_prompt = self.active_system_prompt

        profile_prompt_drafts = self.profile_prompt_drafts.to_dict()

        runtime_draft: dict[str, Any] | None
        if isinstance(self.runtime_draft, PlatformDraftState):
            runtime_draft = self.runtime_draft.to_dict()
        else:
            runtime_draft = self.runtime_draft

        system_prompt_draft: dict[str, Any] | None
        if isinstance(self.system_prompt_draft, PlatformDraftState):
            system_prompt_draft = self.system_prompt_draft.to_dict()
        else:
            system_prompt_draft = self.system_prompt_draft

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "active_profile_prompts": active_profile_prompts,
                "active_release": active_release,
                "active_runtime": active_runtime,
                "active_system_prompt": active_system_prompt,
                "profile_prompt_drafts": profile_prompt_drafts,
                "runtime_draft": runtime_draft,
                "system_prompt_draft": system_prompt_draft,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.platform_draft_state import PlatformDraftState
        from ..models.platform_release_response import PlatformReleaseResponse
        from ..models.platform_state_response_active_profile_prompts import (
            PlatformStateResponseActiveProfilePrompts,
        )
        from ..models.platform_state_response_active_runtime_type_0 import (
            PlatformStateResponseActiveRuntimeType0,
        )
        from ..models.platform_state_response_profile_prompt_drafts import (
            PlatformStateResponseProfilePromptDrafts,
        )

        d = dict(src_dict)
        active_profile_prompts = PlatformStateResponseActiveProfilePrompts.from_dict(
            d.pop("active_profile_prompts")
        )

        def _parse_active_release(data: object) -> None | PlatformReleaseResponse:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                active_release_type_0 = PlatformReleaseResponse.from_dict(data)

                return active_release_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PlatformReleaseResponse, data)

        active_release = _parse_active_release(d.pop("active_release"))

        def _parse_active_runtime(
            data: object,
        ) -> None | PlatformStateResponseActiveRuntimeType0:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                active_runtime_type_0 = (
                    PlatformStateResponseActiveRuntimeType0.from_dict(data)
                )

                return active_runtime_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PlatformStateResponseActiveRuntimeType0, data)

        active_runtime = _parse_active_runtime(d.pop("active_runtime"))

        def _parse_active_system_prompt(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        active_system_prompt = _parse_active_system_prompt(
            d.pop("active_system_prompt")
        )

        profile_prompt_drafts = PlatformStateResponseProfilePromptDrafts.from_dict(
            d.pop("profile_prompt_drafts")
        )

        def _parse_runtime_draft(data: object) -> None | PlatformDraftState:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                runtime_draft_type_0 = PlatformDraftState.from_dict(data)

                return runtime_draft_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PlatformDraftState, data)

        runtime_draft = _parse_runtime_draft(d.pop("runtime_draft"))

        def _parse_system_prompt_draft(data: object) -> None | PlatformDraftState:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                system_prompt_draft_type_0 = PlatformDraftState.from_dict(data)

                return system_prompt_draft_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PlatformDraftState, data)

        system_prompt_draft = _parse_system_prompt_draft(d.pop("system_prompt_draft"))

        platform_state_response = cls(
            active_profile_prompts=active_profile_prompts,
            active_release=active_release,
            active_runtime=active_runtime,
            active_system_prompt=active_system_prompt,
            profile_prompt_drafts=profile_prompt_drafts,
            runtime_draft=runtime_draft,
            system_prompt_draft=system_prompt_draft,
        )

        platform_state_response.additional_properties = d
        return platform_state_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
