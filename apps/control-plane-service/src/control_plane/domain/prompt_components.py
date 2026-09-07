from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, Strict, field_validator

from control_plane.domain.components import (
    ComponentDefinition,
    ComponentDefinitionRegistry,
    ComponentKind,
    ScopeType,
)


class PromptValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, Strict(), Field(max_length=1_000_000)]

    @field_validator("content")
    @classmethod
    def content_is_not_blank(cls, content: str) -> str:
        if not content.strip():
            raise ValueError("content must not be blank")
        return content


class ProfileSelection(BaseModel):
    """The explicit tenant choice of a platform profile prompt."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    profile_key: Annotated[str, Strict(), Field(min_length=1, max_length=255)]


def register_prompt_components(registry: object) -> None:
    assert isinstance(registry, ComponentDefinitionRegistry)
    # Legacy registration; semantic replacement is Slice 7.
    registry.register(
        ComponentDefinition(
            ComponentKind("prompt.system"),
            PromptValue,
            frozenset({ScopeType.PLATFORM}),
            1,
        ),
    )
    # Legacy registration; semantic replacement is Slice 10.
    registry.register(
        ComponentDefinition(
            ComponentKind("prompt.profile.selection"),
            ProfileSelection,
            frozenset({ScopeType.TENANT}),
            1,
        ),
    )
    # Legacy registration; semantic replacement is Slice 7.
    registry.register(
        ComponentDefinition(
            ComponentKind("prompt.profile"),
            PromptValue,
            frozenset({ScopeType.PROFILE}),
            1,
        ),
    )
    # Legacy registration; semantic replacement is Slice 10.
    registry.register(
        ComponentDefinition(
            ComponentKind("prompt.tenant"),
            PromptValue,
            frozenset({ScopeType.TENANT}),
            1,
        ),
    )
