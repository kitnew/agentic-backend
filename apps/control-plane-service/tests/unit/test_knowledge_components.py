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
from control_plane.domain.knowledge_components import (
    TenantKnowledgeValue,
    register_knowledge_components,
)


def test_tenant_knowledge_is_inline_and_tenant_scoped() -> None:
    registry = ComponentRegistry()
    register_knowledge_components(registry)
    address = ComponentAddress(ComponentKind("knowledge.tenant"), TenantScope("a"))
    value = registry.resolve(address).deserialize({"content": "# Café\n\nČas  "})

    assert value.content == "# Café\n\nČas  "
    assert registry.resolve(address).serialize(value) == {"content": "# Café\n\nČas  "}
    with pytest.raises(ScopeNotAllowed):
        registry.resolve(ComponentAddress(address.kind, PlatformScope()))
    with pytest.raises(ScopeNotAllowed):
        registry.resolve(ComponentAddress(address.kind, ProfileScope("hotel")))
    with pytest.raises(InvalidComponentValue):
        registry.resolve(address).deserialize({"content": " \n\t"})
    with pytest.raises(InvalidComponentValue):
        registry.resolve(address).deserialize({"content": 1})
    with pytest.raises(InvalidComponentValue):
        registry.resolve(address).deserialize({"content": "x" * 1_000_001})

    schema = TenantKnowledgeValue.model_json_schema()
    assert not {"artifact_id", "knowledge_base_revision_id", "rag"} & set(schema)
