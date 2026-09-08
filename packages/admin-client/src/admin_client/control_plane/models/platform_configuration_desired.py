from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.desired_interaction_mode import DesiredInteractionMode
    from ..models.desired_profile import DesiredProfile
    from ..models.system_prompt import SystemPrompt


T = TypeVar("T", bound="PlatformConfigurationDesired")


@_attrs_define
class PlatformConfigurationDesired:
    """
    Attributes:
        interaction_modes (list[DesiredInteractionMode]):
        profiles (list[DesiredProfile]):
        system_prompt (SystemPrompt):
    """

    interaction_modes: list[DesiredInteractionMode]
    profiles: list[DesiredProfile]
    system_prompt: SystemPrompt

    def to_dict(self) -> dict[str, Any]:
        interaction_modes = []
        for interaction_modes_item_data in self.interaction_modes:
            interaction_modes_item = interaction_modes_item_data.to_dict()
            interaction_modes.append(interaction_modes_item)

        profiles = []
        for profiles_item_data in self.profiles:
            profiles_item = profiles_item_data.to_dict()
            profiles.append(profiles_item)

        system_prompt = self.system_prompt.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "interaction_modes": interaction_modes,
                "profiles": profiles,
                "system_prompt": system_prompt,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.desired_interaction_mode import DesiredInteractionMode
        from ..models.desired_profile import DesiredProfile
        from ..models.system_prompt import SystemPrompt

        d = dict(src_dict)
        interaction_modes = []
        _interaction_modes = d.pop("interaction_modes")
        for interaction_modes_item_data in _interaction_modes:
            interaction_modes_item = DesiredInteractionMode.from_dict(
                interaction_modes_item_data
            )

            interaction_modes.append(interaction_modes_item)

        profiles = []
        _profiles = d.pop("profiles")
        for profiles_item_data in _profiles:
            profiles_item = DesiredProfile.from_dict(profiles_item_data)

            profiles.append(profiles_item)

        system_prompt = SystemPrompt.from_dict(d.pop("system_prompt"))

        platform_configuration_desired = cls(
            interaction_modes=interaction_modes,
            profiles=profiles,
            system_prompt=system_prompt,
        )

        return platform_configuration_desired
