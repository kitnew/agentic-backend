from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from control_plane.commands.errors import CommandError
from control_plane.workspace.model import (
    LocalResource,
    PlatformResourceKind,
    ResourceId,
    ResourceKind,
    resource_path,
)
from control_plane.workspace.projections import from_local, to_local


def _yaml_load(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except yaml.YAMLError as error:
        raise CommandError(f"invalid YAML: {path}: {error}", 2) from error


def load(root: Path, resource_id: ResourceId) -> LocalResource:
    path = resource_path(root, resource_id)
    if resource_id.kind is ResourceKind.KNOWLEDGE:
        if not path.exists():
            return LocalResource(None, False)
        if not path.is_dir():
            return LocalResource(None, True, False)
        files = {
            str(item.relative_to(path)): item.read_text(encoding="utf-8").replace("\r\n", "\n")
            for item in sorted(path.rglob("*"))
            if item.is_file()
        }
        return LocalResource(from_local(resource_id, files), True)
    if resource_id.kind is ResourceKind.PROMPT:
        if not path.exists():
            return LocalResource(None, False)
        return LocalResource(
            from_local(resource_id, path.read_text(encoding="utf-8").replace("\r\n", "\n")),
            True,
        )
    if resource_id.kind in {PlatformResourceKind.SYSTEM_PROMPT, PlatformResourceKind.PROFILE_PROMPT}:
        if not path.exists():
            return LocalResource(None, False)
        return LocalResource(path.read_text(encoding="utf-8").replace("\r\n", "\n"), True)
    value = _yaml_load(path)
    return LocalResource(value, path.exists(), isinstance(value, dict) or value is None)


def dump(root: Path, resource_id: ResourceId, value: Any) -> dict[Path, str]:
    path = resource_path(root, resource_id)
    projection = to_local(root, resource_id, value)
    if projection is not None:
        return projection
    if resource_id.kind is ResourceKind.KNOWLEDGE:
        raise CommandError(f"invalid knowledge projection: {path}", 2)
    if resource_id.kind in {PlatformResourceKind.SYSTEM_PROMPT, PlatformResourceKind.PROFILE_PROMPT}:
        return {path: str(value).replace("\r\n", "\n")}
    return {path: yaml.safe_dump(value or {}, allow_unicode=True, sort_keys=False)}


def write_atomic(files: dict[Path, str]) -> None:
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.agentctl.tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
