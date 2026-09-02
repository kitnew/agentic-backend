import pytest
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    PlatformScope,
    ProfileScope,
    TenantScope,
)
from control_plane.domain.components.errors import (
    InvalidComponentValue,
    ScopeNotAllowed,
)
from control_plane.domain.prompt_components import (
    PromptValue,
    register_prompt_components,
)


def registry() -> ComponentRegistry:
    result = ComponentRegistry()
    register_prompt_components(result)
    return result


def test_prompt_kinds_are_scope_explicit_and_content_is_lossless() -> None:
    result = registry()
    text = "# Ünïcøde\n\nKeep  spaces and a final newline.\n"
    for kind, scope in (
        ("prompt.system", PlatformScope()),
        ("prompt.profile", ProfileScope("hotel")),
        ("prompt.tenant", TenantScope("tenant-1")),
    ):
        definition = result.resolve(ComponentAddress(ComponentKind(kind), scope))
        value = definition.deserialize({"content": text})
        assert isinstance(value, PromptValue)
        assert value.content == text
        assert definition.serialize(value) == {"content": text}


@pytest.mark.parametrize(
    ("kind", "scope"),
    [
        ("prompt.system", TenantScope("tenant-1")),
        ("prompt.system", ProfileScope("hotel")),
        ("prompt.profile", PlatformScope()),
        ("prompt.profile", TenantScope("tenant-1")),
        ("prompt.tenant", PlatformScope()),
        ("prompt.tenant", ProfileScope("hotel")),
    ],
)
def test_prompt_kinds_reject_invalid_scopes(kind: str, scope: object) -> None:
    with pytest.raises(ScopeNotAllowed):
        registry().resolve(ComponentAddress(ComponentKind(kind), scope))  # type: ignore[arg-type]


@pytest.mark.parametrize("content", ["", " ", "\n\t"])
def test_prompt_content_must_not_be_blank(content: str) -> None:
    with pytest.raises(InvalidComponentValue):
        registry().resolve(
            ComponentAddress(ComponentKind("prompt.system"), PlatformScope())
        ).deserialize({"content": content})


def test_prompt_content_limit_is_finite() -> None:
    with pytest.raises(InvalidComponentValue):
        registry().resolve(
            ComponentAddress(ComponentKind("prompt.system"), PlatformScope())
        ).deserialize({"content": "x" * 1_000_001})


@pytest.mark.parametrize("content", [None, 1])
def test_prompt_content_must_be_a_string(content: object) -> None:
    with pytest.raises(InvalidComponentValue):
        registry().resolve(
            ComponentAddress(ComponentKind("prompt.system"), PlatformScope())
        ).deserialize({"content": content})
