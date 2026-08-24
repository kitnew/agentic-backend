from pathlib import Path

from control_plane.application.workspace import pull
from control_plane.backend.facade import PlanResult
from control_plane.workspace.codecs import dump, load
from control_plane.workspace.model import RemoteAuthoringState, ResourceId, ResourceKind
from control_plane.workspace.state_store import StateStore


def resource(tmp_path: Path, kind: ResourceKind) -> ResourceId:
    return ResourceId("tenant", "hotel", kind)


class Remote:
    def __init__(self, values):
        self.values = values

    def get_state(self, resource_id):
        value = self.values[resource_id]
        return RemoteAuthoringState(value, None, '"1"')

    def plan(self, resource_id, value):
        return PlanResult(True, [], [], [])

    def save(self, resource_id, value, etag):
        return self.get_state(resource_id)

    def publish_all(self, tenant):
        return None


def test_prompt_and_knowledge_use_human_file_shapes(tmp_path: Path) -> None:
    prompt = resource(tmp_path, ResourceKind.PROMPT)
    knowledge = resource(tmp_path, ResourceKind.KNOWLEDGE)

    prompt_files = dump(tmp_path, prompt, {"text": "Welcome to Hotel."})
    knowledge_files = dump(tmp_path, knowledge, {"content": "Breakfast is included."})
    assert prompt_files[tmp_path / "tenants/hotel/tenant_prompt.md"] == "Welcome to Hotel."
    assert list(knowledge_files) == [tmp_path / "tenants/hotel/knowledge/knowledge.md"]
    assert "artifact_id" not in {path.name for path in knowledge_files}

    for path, content in {**prompt_files, **knowledge_files}.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    assert load(tmp_path, prompt).value == {"text": "Welcome to Hotel."}
    assert load(tmp_path, knowledge).value == {"content": "Breakfast is included."}


def test_agent_and_runtime_yaml_round_trip_without_legacy_sections(tmp_path: Path) -> None:
    agent = resource(tmp_path, ResourceKind.AGENT)
    runtime = resource(tmp_path, ResourceKind.RUNTIME)
    agent_value = {
        "agent": {"display_name": "Hotel", "greeting": "Hello", "profile": "default"},
        "business": {"name": "Hotel", "type": "hotel"},
        "conversation": {"scope": "property_only"},
        "localization": {"default_locale": "en-US", "timezone": "UTC"},
        "contact": {"address": None, "phones": [], "emails": [], "website": None},
        "handoff": {"destinations": {}},
    }
    runtime_value = {"llm": None, "tts": None}
    for resource_id, candidate in ((agent, agent_value), (runtime, runtime_value)):
        files = dump(tmp_path, resource_id, candidate)
        text = "\n".join(files.values())
        assert "schema_version" not in text
        assert "capabilities" not in text
        assert "post_call" not in text
        assert "telephony" not in text
        for path, content in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        assert load(tmp_path, resource_id).value == candidate


def test_fresh_pull_materializes_all_six_tenant_projections(tmp_path: Path) -> None:
    values = {
        ResourceKind.AGENT: {"agent": {}, "business": {}, "conversation": {}, "localization": {}, "contact": {}, "handoff": {}},
        ResourceKind.RUNTIME: {"llm": None, "tts": None},
        ResourceKind.PROMPT: {"text": ""},
        ResourceKind.KNOWLEDGE: {"content": ""},
        ResourceKind.CAPABILITIES: {"capabilities": {}},
        ResourceKind.POST_CALL: {"actions": []},
    }
    remote = Remote({resource(tmp_path, kind): value for kind, value in values.items()})
    pull(tmp_path, StateStore(tmp_path, "https://backend.example"), remote, "hotel")
    assert {
        path.relative_to(tmp_path).as_posix()
        for path in (tmp_path / "tenants/hotel").rglob("*")
        if path.is_file()
    } == {
        "tenants/hotel/tenant.yaml",
        "tenants/hotel/runtime.yaml",
        "tenants/hotel/tenant_prompt.md",
        "tenants/hotel/knowledge/knowledge.md",
        "tenants/hotel/capabilities.yaml",
        "tenants/hotel/post_call.yaml",
    }


def test_pull_materializes_valid_empty_agent_value(tmp_path: Path) -> None:
    agent = resource(tmp_path, ResourceKind.AGENT)
    remote = Remote(
        {
            agent: {},
            resource(tmp_path, ResourceKind.RUNTIME): {"llm": None, "tts": None},
            resource(tmp_path, ResourceKind.PROMPT): {"text": ""},
            resource(tmp_path, ResourceKind.KNOWLEDGE): {"content": ""},
            resource(tmp_path, ResourceKind.CAPABILITIES): {"capabilities": {}},
            resource(tmp_path, ResourceKind.POST_CALL): {"actions": []},
        }
    )

    pull(tmp_path, StateStore(tmp_path, "https://backend.example"), remote, "hotel")

    path = tmp_path / "tenants/hotel/tenant.yaml"
    assert path.exists()
    assert load(tmp_path, agent).present
    assert load(tmp_path, agent).value == {}


def test_capability_and_post_call_yaml_keep_operator_metadata_only(tmp_path: Path) -> None:
    capability = resource(tmp_path, ResourceKind.CAPABILITIES)
    post_call = resource(tmp_path, ResourceKind.POST_CALL)
    value = {
        "capabilities": {
            "reservation.check_availability": {
                "description": "Check availability",
                "announcement": "Checking",
                "agent_input_schema": {"type": "object"},
                "bindings": {"check_in": "stay.check_in"},
                "execution": {
                    "connection": "check-availability",
                    "method": "POST",
                    "request": {
                        "codec": "json",
                        "mapping": {"id": {"$expr": "business.id"}},
                    },
                    "response": {"codec": "none"},
                    "timeout_seconds": 10,
                },
            }
        }
    }
    action = {
        "actions": [
            {
                "action_id": "send_transcript",
                "inputs": {"transcript": {"artifact": "transcript", "representation": "plain_text"}},
                "semantic_key": "post_call.transcript",
                "semantic_version": 1,
                "execution": {
                    "connection": "post-call",
                    "method": "POST",
                    "request": {"codec": "none"},
                    "response": {"codec": "none"},
                    "timeout_seconds": 10,
                },
            }
        ]
    }
    for resource_id, candidate in ((capability, value), (post_call, action)):
        files = dump(tmp_path, resource_id, candidate)
        text = "\n".join(files.values())
        assert "connection_id" not in text
        assert "http.request.v1" not in text
        assert "mapping_engine" not in text
        for path, content in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        assert load(tmp_path, resource_id).value == candidate
