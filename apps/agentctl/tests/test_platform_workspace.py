from agentctl.backend.generated import GeneratedPlatformRemoteAdapter
from agentctl.workspace.model import (
    PlatformResourceKind,
    ResourceId,
    WorkspaceResourceKind,
)


class CP:
    def __init__(self):
        self.published = []
        self.read = []

    def get_configuration(self, scope):
        self.read.append(scope)
        return type(
            "State",
            (),
            {
                "value": {
                    "stt_defaults": {"deployment_ref": "x"},
                    "status": {"has_drafts": False},
                    "system_prompt": {"active": {"content": "héllo"}},
                    "profiles": [
                        {
                            "key": "concierge",
                            "prompt": {"active": {"content": "héllo"}},
                        }
                    ],
                },
                "write_etag": '"opaque"',
            },
        )()

    def save_component(self, *args, **kwargs):
        pass

    def publish_component(self, kind, version, **kwargs):
        self.published.append((kind, version))


def test_system_configuration_applies_without_publish():
    cp = CP()
    adapter = GeneratedPlatformRemoteAdapter(cp)
    resource = ResourceId(
        "platform", "platform", WorkspaceResourceKind.PLATFORM_RUNTIME_STT
    )
    adapter.publish_component(resource)
    assert cp.published == []


def test_profile_prompt_has_independent_cp_scope():
    cp = CP()
    adapter = GeneratedPlatformRemoteAdapter(cp)
    adapter.get_state(
        ResourceId(
            "platform", "platform", PlatformResourceKind.PROFILE_PROMPT, "concierge"
        )
    )
    assert cp.read == ["platform"]
