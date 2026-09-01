import pytest
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinition,
    ComponentKind,
    ComponentRegistry,
    ComponentState,
    PlatformScope,
    ScopeType,
    TenantScope,
)
from control_plane.domain.components.errors import (
    InvalidComponentValue,
    ScopeNotAllowed,
    UnknownComponentKind,
)
from pydantic import BaseModel


class ExampleSettings(BaseModel):
    enabled: bool
    label: str


def definition() -> ComponentDefinition[ExampleSettings]:
    return ComponentDefinition(
        ComponentKind("example.settings"),
        ExampleSettings,
        frozenset({ScopeType.TENANT}),
        1,
    )


def test_registry_validation_and_serialization() -> None:
    registry = ComponentRegistry()
    registry.register(definition())
    address = ComponentAddress(
        ComponentKind("example.settings"), TenantScope("tenant-1")
    )
    resolved = registry.resolve(address)
    value = resolved.deserialize({"enabled": True, "label": "demo"})
    assert isinstance(value, ExampleSettings)
    assert resolved.serialize(value) == {"enabled": True, "label": "demo"}

    with pytest.raises(ValueError, match="duplicate"):
        registry.register(definition())
    with pytest.raises(UnknownComponentKind):
        ComponentRegistry().resolve(address)
    with pytest.raises(ScopeNotAllowed):
        registry.resolve(ComponentAddress(address.kind, PlatformScope()))
    with pytest.raises(InvalidComponentValue):
        resolved.deserialize({"enabled": "not-a-bool", "label": "demo"})


@pytest.mark.parametrize(
    ("active", "draft", "state"),
    [
        (False, False, ComponentState.EMPTY),
        (False, True, ComponentState.DRAFT_ONLY),
        (True, False, ComponentState.PUBLISHED),
        (True, True, ComponentState.MODIFIED),
    ],
)
def test_component_state_is_derived(
    active: bool, draft: bool, state: ComponentState
) -> None:
    assert ComponentState.derive(has_active=active, has_draft=draft) is state
