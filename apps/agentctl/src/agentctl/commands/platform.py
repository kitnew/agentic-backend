from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from agentctl.commands.errors import CommandError
from agentctl.control_plane import ControlPlaneClient
from agentctl.settings import Settings

RUNTIME_KINDS = {
    "llm": "runtime.llm.defaults",
    "stt": "runtime.stt.defaults",
    "tts": "runtime.tts.defaults",
    "cascade": "runtime.cascade.execution.defaults",
    "realtime": "runtime.realtime.execution.defaults",
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise CommandError(f"missing authoring file: {path}", 2) from None


def _content(state: Any) -> str:
    value = state.working or {}
    return value.get("content", "") if isinstance(value, dict) else str(value)


def _text(value: Any) -> str:
    return value.get("content", "") if isinstance(value, dict) else str(value or "")


def _prompt(settings: Settings, action: str, kind: str, path: Path, *, profile_key: str | None = None, revision_number: int | None = None) -> None:
    with ControlPlaneClient(settings) as client:
        state = client.get_component(kind, profile_key=profile_key)
        if action == "show":
            print(_content(state) or "No active prompt.")
        elif action == "pull":
            if path.exists():
                raise CommandError(f"refusing to overwrite existing file: {path}", 2)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_text(state.working), encoding="utf-8")
        elif action == "push":
            value = _read(path)
            client.save_component(
                kind,
                {"content": value},
                draft_version=state.draft_version,
                active_revision_id=state.active_revision_id,
                profile_key=profile_key,
            )
            print("Saved Control Plane draft.")
        elif action == "publish":
            if state.draft_version is None:
                print("No saved draft to publish.")
            else:
                client.publish_component(kind, state.draft_version, profile_key=profile_key)
                print("Published Control Plane component.")
        elif action == "revisions":
            for revision in client.revisions(kind, profile_key=profile_key):
                print(revision)
        elif action == "rollback":
            if revision_number is None:
                raise CommandError("revision number is required", 2)
            print(client.rollback(kind, revision_number, profile_key=profile_key))
        else:
            raise CommandError(f"unsupported prompt action: {action}", 2)


def run_system_prompt(settings: Settings, action: str, *, force: bool = False, revision_number: int | None = None) -> None:
    _prompt(settings, action, "prompt.system", settings.state_dir / "platform" / "system_prompt.md", revision_number=revision_number)


def run_profile(settings: Settings, action: str, profile: str | None, *, force: bool = False, revision_number: int | None = None) -> None:
    if profile is None:
        raise CommandError("profile key is required", 2)
    _prompt(
        settings,
        action,
        "prompt.profile",
        settings.state_dir / "platform" / "profiles" / f"{profile}.md",
        profile_key=profile,
        revision_number=revision_number,
    )


def run_platform_runtime(settings: Settings, action: str, *, force: bool = False, component: str | None = None, revision_number: int | None = None) -> None:
    path = settings.state_dir / "platform" / "runtime.yaml"
    with ControlPlaneClient(settings) as client:
        states = {name: client.get_component(kind) for name, kind in RUNTIME_KINDS.items()}
        if action == "show":
            print(yaml.safe_dump({name: state.working for name, state in states.items() if state.working is not None}, sort_keys=False), end="")
        elif action == "pull":
            if path.exists() and not force:
                raise CommandError(f"refusing to overwrite existing file: {path}", 2)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump({name: state.working for name, state in states.items() if state.working is not None}, sort_keys=False), encoding="utf-8")
        elif action == "push":
            try:
                value = yaml.safe_load(_read(path))
            except yaml.YAMLError as error:
                raise CommandError(f"invalid runtime YAML: {error}", 2) from error
            if not isinstance(value, dict):
                raise CommandError("runtime YAML root must be a mapping", 2)
            for name, payload in value.items():
                if name not in RUNTIME_KINDS:
                    raise CommandError(f"unknown runtime component: {name}", 2)
                client.save_component(
                    RUNTIME_KINDS[name],
                    payload,
                    draft_version=states[name].draft_version,
                    active_revision_id=states[name].active_revision_id,
                )
            print("Saved Control Plane runtime draft.")
        elif action == "publish":
            dirty = [name for name, state in states.items() if state.draft_version is not None]
            if not dirty:
                print("No saved runtime draft to publish.")
            else:
                for name in dirty:
                    version = states[name].draft_version
                    assert version is not None
                    client.publish_component(RUNTIME_KINDS[name], version)
                print("Published Control Plane runtime components: " + ", ".join(dirty))
        elif action == "revisions":
            selected = {component: RUNTIME_KINDS[component]} if component else RUNTIME_KINDS
            for name, kind in selected.items():
                print(f"[{name}]")
                for revision in client.revisions(kind):
                    print(revision)
        elif action == "rollback":
            if component is None or revision_number is None:
                raise CommandError("runtime component and revision number are required", 2)
            print(client.rollback(RUNTIME_KINDS[component], revision_number))
        else:
            raise CommandError(f"unsupported runtime action: {action}", 2)
