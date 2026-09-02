from pathlib import Path

from agentctl.application.workspace import pull
from agentctl.backend.facade import PlanResult
from agentctl.workspace.codecs import dump, load
from agentctl.workspace.model import (
    RemoteAuthoringState,
    ResourceId,
    WorkspaceResourceKind,
)
from agentctl.workspace.state_store import StateStore


def resource(kind: WorkspaceResourceKind) -> ResourceId:
    return ResourceId("tenant", "hotel", kind)


def test_profile_selection_and_agent_profile_are_separate_files():
    root = Path("definitions")
    agent = resource(WorkspaceResourceKind.AGENT)
    selection = resource(WorkspaceResourceKind.PROMPT_PROFILE_SELECTION)
    assert dump(root, agent, {"agent_profile": "concierge"})[root / "tenants/hotel/agent.yaml"]
    assert dump(root, selection, {"profile_key": "default"})[root / "tenants/hotel/prompt/profile_selection.yaml"]


def test_prompt_and_knowledge_preserve_unicode_markdown(tmp_path: Path):
    prompt = resource(WorkspaceResourceKind.PROMPT_TENANT)
    knowledge = resource(WorkspaceResourceKind.KNOWLEDGE)
    prompt_file = dump(tmp_path, prompt, {"content": "Penzión\n**Grand**"})
    knowledge_file = dump(tmp_path, knowledge, {"content": "Kováčska\n- volské oko"})
    for files in (prompt_file, knowledge_file):
        for path, text in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    assert load(tmp_path, prompt).value == {"content": "Penzión\n**Grand**"}
    assert load(tmp_path, knowledge).value == {"content": "Kováčska\n- volské oko"}


class Remote:
    def __init__(self, values): self.values = values
    def get_state(self, resource_id): return RemoteAuthoringState(self.values[resource_id], self.values[resource_id], '"1"')
    def plan(self, resource_id, value): return PlanResult(True, [], [], [])
    def save(self, resource_id, value, etag): return self.get_state(resource_id)
    def publish_all(self, tenant): return None


def test_pull_materializes_all_cp_tenant_components(tmp_path: Path):
    values = {resource(kind): {} for kind in WorkspaceResourceKind if kind.value.startswith("workspace_") and kind not in {WorkspaceResourceKind.PROMPT_TENANT, WorkspaceResourceKind.KNOWLEDGE}}
    values[resource(WorkspaceResourceKind.PROMPT_TENANT)] = {"content": "hello"}
    values[resource(WorkspaceResourceKind.KNOWLEDGE)] = {"content": "knowledge"}
    pull(tmp_path, StateStore(tmp_path, "https://backend"), Remote(values), "hotel")
    assert (tmp_path / "tenants/hotel/agent.yaml").exists()
    assert (tmp_path / "tenants/hotel/prompt/tenant.md").read_text() == "hello"
    assert (tmp_path / "tenants/hotel/knowledge.md").read_text() == "knowledge"
