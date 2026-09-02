import pytest
from control_plane.domain.agent_components import (
    TenantAgentValue,
    register_agent_components,
)
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    ProfileScope,
    TenantScope,
)
from control_plane.domain.components.errors import (
    InvalidComponentValue,
    ScopeNotAllowed,
)


def registry() -> ComponentRegistry:
    result = ComponentRegistry()
    register_agent_components(result)
    return result


def value() -> dict[str, object]:
    return {
        "display_name": "Amélia",
        "agent_profile": "default",
        "greeting": "Dobrý deň, víta vás Penzión Grand 🌿",
        "conversation_scope": "property_only",
        "locale": "sk-SK",
        "timezone": "Europe/Bratislava",
    }


def test_agent_component_is_tenant_only_and_round_trips_exactly() -> None:
    definition = registry().resolve(
        ComponentAddress(ComponentKind("agent.tenant"), TenantScope("tenant-a"))
    )

    typed = definition.deserialize(value())

    assert isinstance(typed, TenantAgentValue)
    assert typed.model_dump(mode="json") == value()


def test_agent_component_rejects_invalid_locale_timezone_and_profile() -> None:
    definition = registry().resolve(
        ComponentAddress(ComponentKind("agent.tenant"), TenantScope("tenant-a"))
    )
    for field, invalid in (
        ("locale", "sk_sk"),
        ("timezone", "Not/AZone"),
        ("agent_profile", "Default"),
    ):
        payload = value()
        payload[field] = invalid
        with pytest.raises(InvalidComponentValue):
            definition.deserialize(payload)


def test_agent_component_requires_all_six_fields() -> None:
    definition = registry().resolve(
        ComponentAddress(ComponentKind("agent.tenant"), TenantScope("tenant-a"))
    )
    with pytest.raises(InvalidComponentValue):
        definition.deserialize({key: value()[key] for key in value() if key != "greeting"})


def test_agent_component_rejects_profile_scope() -> None:
    with pytest.raises(ScopeNotAllowed):
        registry().resolve(
            ComponentAddress(ComponentKind("agent.tenant"), ProfileScope("default"))
        )
