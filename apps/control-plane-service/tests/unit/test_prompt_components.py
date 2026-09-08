import pytest
from control_plane.application.execution_resolver import compose_instructions
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
    ComponentKind,
    InteractionModeScope,
    PlatformScope,
    ProfileScope,
    TenantScope,
)
from control_plane.domain.components.errors import (
    InvalidComponentValue,
    ScopeNotAllowed,
)
from control_plane.domain.frozen_components import (
    InteractionPrompt,
    ProfilePrompt,
    SystemPrompt,
)
from control_plane.domain.prompt_components import (
    PromptValue,
    register_prompt_components,
)


def registry() -> ComponentDefinitionRegistry:
    result = ComponentDefinitionRegistry()
    register_prompt_components(result)
    return result


def test_prompt_kinds_are_scope_explicit_and_content_is_lossless() -> None:
    result = registry()
    text = "# Ünïcøde\n\nKeep  spaces and a final newline.\n"
    for kind, scope, value_type in (
        ("SystemPrompt", PlatformScope(), SystemPrompt),
        ("ProfilePrompt", ProfileScope("hotel"), ProfilePrompt),
        ("InteractionPrompt", InteractionModeScope("voice"), InteractionPrompt),
        ("prompt.tenant", TenantScope("tenant-1"), PromptValue),
    ):
        definition = result.resolve(ComponentAddress(ComponentKind(kind), scope))
        value = definition.deserialize({"content": text})
        assert isinstance(value, value_type)
        assert value.content == text
        assert definition.serialize(value) == {"content": text}


def test_profile_selection_is_explicit_and_prompt_composition_is_lossless() -> None:
    selection = (
        registry()
        .resolve(
            ComponentAddress(
                ComponentKind("prompt.profile.selection"), TenantScope("t")
            )
        )
        .deserialize({"profile_key": "hotel"})
    )
    assert selection.profile_key == "hotel"
    assert compose_instructions("System\n", "Profile", "", "Knowledge\n") == (
        "System\n\n\nProfile\n\nKnowledge\n"
    )


@pytest.mark.parametrize(
    ("kind", "scope"),
    [
        ("SystemPrompt", TenantScope("tenant-1")),
        ("SystemPrompt", ProfileScope("hotel")),
        ("ProfilePrompt", PlatformScope()),
        ("ProfilePrompt", TenantScope("tenant-1")),
        ("InteractionPrompt", ProfileScope("hotel")),
        ("prompt.tenant", PlatformScope()),
        ("prompt.tenant", ProfileScope("hotel")),
    ],
)
def test_prompt_kinds_reject_invalid_scopes(kind: str, scope: object) -> None:
    with pytest.raises(ScopeNotAllowed):
        registry().resolve(ComponentAddress(ComponentKind(kind), scope))  # type: ignore[arg-type]


@pytest.mark.parametrize("content", [""])
def test_prompt_content_must_not_be_blank(content: str) -> None:
    with pytest.raises(InvalidComponentValue):
        registry().resolve(
            ComponentAddress(ComponentKind("SystemPrompt"), PlatformScope())
        ).deserialize({"content": content})


def test_prompt_content_has_no_undocumented_size_limit() -> None:
    value = (
        registry()
        .resolve(ComponentAddress(ComponentKind("SystemPrompt"), PlatformScope()))
        .deserialize({"content": "x" * 1_000_001})
    )
    assert len(value.content) == 1_000_001


@pytest.mark.parametrize("content", [None, 1])
def test_prompt_content_must_be_a_string(content: object) -> None:
    with pytest.raises(InvalidComponentValue):
        registry().resolve(
            ComponentAddress(ComponentKind("SystemPrompt"), PlatformScope())
        ).deserialize({"content": content})
