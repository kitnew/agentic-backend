from pathlib import Path

import pytest
from agentctl.application.workspace import PublishReport, publish_many
from agentctl.backend.facade import PlanResult
from agentctl.commands.errors import CommandError
from agentctl.workspace.model import (
    RemoteAuthoringState,
    ResourceId,
    WorkspaceResourceKind,
)
from agentctl.workspace.state_store import StateStore


class Remote:
    def __init__(self, fail=None): self.fail = fail; self.calls = []
    def get_state(self, resource_id):
        value = {"content": "knowledge"} if resource_id.kind is WorkspaceResourceKind.KNOWLEDGE else {"v": 1}
        return RemoteAuthoringState(value, {"v": 0}, '"2"')
    def plan(self, resource_id, value): return PlanResult(True, [], [], [])
    def save(self, resource_id, value, etag): return self.get_state(resource_id)
    def publish_component(self, resource_id):
        self.calls.append(resource_id)
        if resource_id.kind is self.fail: raise CommandError("conflict", 3)


def test_publish_reports_independent_component_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = StateStore(tmp_path, "https://cp")
    remote = Remote(fail=WorkspaceResourceKind.RUNTIME_SPEECH)
    monkeypatch.setattr(
        "agentctl.application.workspace.selected",
        lambda *_: (
            ResourceId("tenant", "hotel", WorkspaceResourceKind.AGENT),
            ResourceId("tenant", "hotel", WorkspaceResourceKind.RUNTIME_SPEECH),
            ResourceId("tenant", "hotel", WorkspaceResourceKind.KNOWLEDGE),
        ),
    )
    monkeypatch.setattr(
        "agentctl.application.workspace.statuses",
        lambda *_: [
            type("Status", (), {"resource_id": resource_id, "local": "present", "synchronization": "clean", "publication": "unpublished"})()
            for resource_id in (
                ResourceId("tenant", "hotel", WorkspaceResourceKind.AGENT),
                ResourceId("tenant", "hotel", WorkspaceResourceKind.RUNTIME_SPEECH),
                ResourceId("tenant", "hotel", WorkspaceResourceKind.KNOWLEDGE),
            )
        ],
    )
    report = publish_many(tmp_path, store, (type("Target", (), {"name": "hotel", "remote": remote})(),))
    assert isinstance(report, PublishReport)
    assert report.failed == "hotel:workspace_runtime_speech"
    assert report.not_attempted == ("hotel:workspace_knowledge",)
