from __future__ import annotations

from pathlib import Path
from typing import Any

from control_plane.commands.errors import CommandError
from control_plane.workspace.model import (
    PlatformResourceKind,
    ResourceId,
    ResourceKind,
    resource_path,
)


def from_local(resource_id: ResourceId, value: Any) -> Any:
    if resource_id.kind in {
        ResourceKind.PROMPT,
        PlatformResourceKind.SYSTEM_PROMPT,
        PlatformResourceKind.PROFILE_PROMPT,
    }:
        return {"text": value}
    if resource_id.kind is ResourceKind.KNOWLEDGE:
        return {"content": value.get("knowledge.md", "")}
    return value


def to_local(root: Path, resource_id: ResourceId, value: Any) -> dict[Path, str] | None:
    path = resource_path(root, resource_id)
    if resource_id.kind is ResourceKind.PROMPT:
        if not isinstance(value, dict) or not isinstance(value.get("text"), str):
            raise CommandError(f"invalid prompt projection: {path}", 2)
        return {path: value["text"].replace("\r\n", "\n")}
    if resource_id.kind is ResourceKind.KNOWLEDGE:
        if not isinstance(value, dict) or not isinstance(value.get("content"), str):
            raise CommandError(f"invalid knowledge projection: {path}", 2)
        return {
            path / "knowledge.md": value["content"].replace("\r\n", "\n")
        }
    if resource_id.kind in {
        PlatformResourceKind.SYSTEM_PROMPT,
        PlatformResourceKind.PROFILE_PROMPT,
    }:
        return None
    return None
