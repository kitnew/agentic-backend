from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from agentctl.commands.errors import CommandError
from agentctl.control_plane import ControlPlaneClient
from agentctl.settings import Settings

RUNTIME_KINDS = {
    "llm": "llm_defaults",
    "stt": "stt_defaults",
    "tts": "tts_defaults",
    "cascade": "policies",
    "realtime": "realtime_defaults",
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise CommandError(f"missing authoring file: {path}", 2) from None


def _text(value: Any) -> str:
    return value.get("content", "") if isinstance(value, dict) else str(value or "")


def _selected(value: dict[str, Any]) -> Any:
    return value.get("draft") or value.get("active")


def _platform_desired(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "system_prompt": _selected(value["system_prompt"]),
        "profiles": [
            {**profile, "prompt": _selected(profile["prompt"])}
            for profile in value["profiles"]
        ],
        "interaction_modes": [
            {**mode, "prompt": _selected(mode["prompt"])}
            for mode in value["interaction_modes"]
        ],
    }


def _prompt(
    settings: Settings,
    action: str,
    kind: str,
    path: Path,
    *,
    profile_key: str | None = None,
    revision_number: int | None = None,
) -> None:
    with ControlPlaneClient(settings) as client:
        configuration = client.get_configuration("platform")
        prompt = (
            configuration.value["system_prompt"]
            if profile_key is None
            else next(
                profile["prompt"]
                for profile in configuration.value["profiles"]
                if profile["key"] == profile_key
            )
        )
        if action == "show":
            print(_text(_selected(prompt)) or "No active prompt.")
        elif action == "pull":
            if path.exists():
                raise CommandError(f"refusing to overwrite existing file: {path}", 2)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_text(_selected(prompt)), encoding="utf-8")
        elif action == "push":
            value = _read(path)
            desired = _platform_desired(configuration.value)
            if profile_key is None:
                desired["system_prompt"] = {"content": value}
            else:
                profile = next(
                    item for item in desired["profiles"] if item["key"] == profile_key
                )
                profile["prompt"] = {"content": value}
            client.apply_configuration("platform", desired, configuration.write_etag)
            print("Saved Control Plane draft.")
        elif action == "publish":
            if not configuration.value["status"]["has_drafts"]:
                print("No saved draft to publish.")
            else:
                client.publish_configuration("platform", configuration.write_etag)
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


def run_system_prompt(
    settings: Settings,
    action: str,
    *,
    force: bool = False,
    revision_number: int | None = None,
) -> None:
    _prompt(
        settings,
        action,
        "SystemPrompt",
        settings.state_dir / "platform" / "system_prompt.md",
        revision_number=revision_number,
    )


def run_profile(
    settings: Settings,
    action: str,
    profile: str | None,
    *,
    force: bool = False,
    revision_number: int | None = None,
) -> None:
    if profile is None:
        raise CommandError("profile key is required", 2)
    _prompt(
        settings,
        action,
        "ProfilePrompt",
        settings.state_dir / "platform" / "profiles" / f"{profile}.md",
        profile_key=profile,
        revision_number=revision_number,
    )


def run_platform_runtime(
    settings: Settings,
    action: str,
    *,
    force: bool = False,
    component: str | None = None,
    revision_number: int | None = None,
) -> None:
    path = settings.state_dir / "platform" / "runtime.yaml"
    with ControlPlaneClient(settings) as client:
        state = client.get_configuration("system")
        current = {name: state.value[field] for name, field in RUNTIME_KINDS.items()}
        if action == "show":
            print(yaml.safe_dump(current, sort_keys=False), end="")
        elif action == "pull":
            if path.exists() and not force:
                raise CommandError(f"refusing to overwrite existing file: {path}", 2)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                yaml.safe_dump(current, sort_keys=False),
                encoding="utf-8",
            )
        elif action == "push":
            try:
                value = yaml.safe_load(_read(path))
            except yaml.YAMLError as error:
                raise CommandError(f"invalid runtime YAML: {error}", 2) from error
            if not isinstance(value, dict):
                raise CommandError("runtime YAML root must be a mapping", 2)
            desired = dict(state.value)
            for name, payload in value.items():
                if name not in RUNTIME_KINDS:
                    raise CommandError(f"unknown runtime component: {name}", 2)
                desired[RUNTIME_KINDS[name]] = payload
            client.apply_configuration("system", desired, state.write_etag)
            print("Applied Control Plane system configuration.")
        else:
            raise CommandError(f"unsupported runtime action: {action}", 2)
