from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.configuration_status import ConfigurationStatus
    from ..models.interaction_mode_configuration import InteractionModeConfiguration
    from ..models.profile_configuration import ProfileConfiguration
    from ..models.prompt_state_system_prompt import PromptStateSystemPrompt


T = TypeVar("T", bound="PlatformConfiguration")


@_attrs_define
class PlatformConfiguration:
    """
    Attributes:
        interaction_modes (list[InteractionModeConfiguration]):
        profiles (list[ProfileConfiguration]):
        status (ConfigurationStatus):
        system_prompt (PromptStateSystemPrompt):
    """

    interaction_modes: list[InteractionModeConfiguration]
    profiles: list[ProfileConfiguration]
    status: ConfigurationStatus
    system_prompt: PromptStateSystemPrompt

    def to_dict(self) -> dict[str, Any]:
        interaction_modes = []
        for interaction_modes_item_data in self.interaction_modes:
            interaction_modes_item = interaction_modes_item_data.to_dict()
            interaction_modes.append(interaction_modes_item)

        profiles = []
        for profiles_item_data in self.profiles:
            profiles_item = profiles_item_data.to_dict()
            profiles.append(profiles_item)

        status = self.status.to_dict()

        system_prompt = self.system_prompt.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "interaction_modes": interaction_modes,
                "profiles": profiles,
                "status": status,
                "system_prompt": system_prompt,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.configuration_status import ConfigurationStatus
        from ..models.interaction_mode_configuration import InteractionModeConfiguration
        from ..models.profile_configuration import ProfileConfiguration
        from ..models.prompt_state_system_prompt import PromptStateSystemPrompt

        d = dict(src_dict)
        interaction_modes = []
        _interaction_modes = d.pop("interaction_modes")
        for interaction_modes_item_data in _interaction_modes:
            interaction_modes_item = InteractionModeConfiguration.from_dict(
                interaction_modes_item_data
            )

            interaction_modes.append(interaction_modes_item)

        profiles = []
        _profiles = d.pop("profiles")
        for profiles_item_data in _profiles:
            profiles_item = ProfileConfiguration.from_dict(profiles_item_data)

            profiles.append(profiles_item)

        status = ConfigurationStatus.from_dict(d.pop("status"))

        system_prompt = PromptStateSystemPrompt.from_dict(d.pop("system_prompt"))

        platform_configuration = cls(
            interaction_modes=interaction_modes,
            profiles=profiles,
            status=status,
            system_prompt=system_prompt,
        )

        return platform_configuration
