
from agentctl.backend.generated import GeneratedPlatformRemoteAdapter
from agentctl.workspace.model import (
    PlatformResourceKind,
    ResourceId,
    WorkspaceResourceKind,
)


class CP:
    def __init__(self): self.published = []
    def get_component(self, kind, **kwargs):
        return type("State", (), {"working": {"content": "héllo"} if kind.startswith("prompt") else {"deployment_ref": "x"}, "active": {"content": "héllo"}, "draft_version": 2})()
    def save_component(self, *args, **kwargs): pass
    def publish_component(self, kind, version, **kwargs): self.published.append((kind, version))


def test_platform_runtime_is_component_specific():
    cp = CP()
    adapter = GeneratedPlatformRemoteAdapter(cp)
    resource = ResourceId("platform", "platform", WorkspaceResourceKind.PLATFORM_RUNTIME_STT)
    adapter.publish_component(resource)
    assert cp.published == [("runtime.stt.defaults", 2)]


def test_profile_prompt_has_independent_cp_scope():
    cp = CP()
    adapter = GeneratedPlatformRemoteAdapter(cp)
    adapter.get_state(ResourceId("platform", "platform", PlatformResourceKind.PROFILE_PROMPT, "concierge"))
    assert cp.published == []
