import pytest
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
    ComponentKind,
    PlatformScope,
    SystemScope,
    TenantScope,
)
from control_plane.domain.components.errors import ScopeNotAllowed, UnknownComponentKind
from control_plane.domain.runtime_components import register_runtime_components


def test_runtime_registry_replaces_legacy_system_kinds_with_frozen_live_kinds() -> None:
    registry = ComponentDefinitionRegistry()
    register_runtime_components(registry)
    for kind in (
        "STTDefaults",
        "LLMDefaults",
        "TTSDefaults",
        "RealtimeDefaults",
        "Policies",
    ):
        definition = registry.resolve(
            ComponentAddress(ComponentKind(kind), SystemScope())
        )
        assert definition.metadata["lifecycle"] == "live"
        with pytest.raises(ScopeNotAllowed):
            registry.resolve(ComponentAddress(ComponentKind(kind), PlatformScope()))
    for kind in (
        "runtime.stt.defaults",
        "runtime.llm.defaults",
        "runtime.tts.defaults",
        "runtime.cascade.execution.defaults",
        "runtime.realtime.execution.defaults",
    ):
        with pytest.raises(UnknownComponentKind):
            registry.resolve(ComponentAddress(ComponentKind(kind), PlatformScope()))


def test_slice10_tenant_runtime_registrations_remain_untouched() -> None:
    registry = ComponentDefinitionRegistry()
    register_runtime_components(registry)
    for kind in ("runtime.architecture.policy", "runtime.speech.overrides"):
        assert registry.resolve(
            ComponentAddress(ComponentKind(kind), TenantScope("tenant"))
        )
