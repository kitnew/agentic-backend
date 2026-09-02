from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from agentctl.workspace.model import RemoteAuthoringState, ResourceId


@dataclass(frozen=True, slots=True)
class PlanResult:
    valid: bool
    changes: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    errors: list[dict[str, Any]]


class RemoteAuthoringAdapter(Protocol):
    def list_resources(self, scope: str) -> tuple[ResourceId, ...]: ...

    def get_state(self, resource_id: ResourceId) -> RemoteAuthoringState: ...
    def plan(self, resource_id: ResourceId, value: Any) -> PlanResult: ...
    def save(self, resource_id: ResourceId, value: Any, etag: str | None) -> RemoteAuthoringState: ...
    def publish_component(self, resource_id: ResourceId) -> Any: ...
