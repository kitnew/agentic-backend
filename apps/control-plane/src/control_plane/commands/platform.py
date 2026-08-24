from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from admin_client.generated.api.adminplatform_components import (
    publish_admin_v1_platform_components_publish_post,
    save_profile_prompt_admin_v1_platform_components_profiles_profile_draft_put,
    save_runtime_admin_v1_platform_components_runtime_draft_put,
    save_system_prompt_admin_v1_platform_components_system_prompt_draft_put,
    state_admin_v1_platform_components_state_get,
)
from admin_client.generated.models.platform_publish_request import (
    PlatformPublishRequest,
)
from admin_client.generated.models.platform_publish_request_profile_prompt_versions import (
    PlatformPublishRequestProfilePromptVersions,
)
from admin_client.generated.models.prompt_draft_write import PromptDraftWrite
from admin_client.generated.models.runtime_draft_write import RuntimeDraftWrite

from control_plane.commands.common import _client, _response_error
from control_plane.commands.errors import CommandError
from control_plane.settings import Settings


def _state(client):
    response = state_admin_v1_platform_components_state_get.sync_detailed(client=client)
    _response_error(response)
    if response.parsed is None:
        raise CommandError("unexpected client failure: invalid platform state", 1)
    return response.parsed


def _read(path: Path, required: bool = True) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if not required:
            return None
        raise CommandError(f"missing authoring file: {path}", 2) from None


def _save_prompt(settings: Settings, profile: str | None, text: str, version: int | None) -> None:
    with _client(settings) as client:
        if profile is None:
            response = save_system_prompt_admin_v1_platform_components_system_prompt_draft_put.sync_detailed(
                client=client, body=PromptDraftWrite(text=text), if_match=None if version is None else f'"{version}"'
            )
        else:
            response = save_profile_prompt_admin_v1_platform_components_profiles_profile_draft_put.sync_detailed(
                profile, client=client, body=PromptDraftWrite(text=text), if_match=None if version is None else f'"{version}"'
            )
        _response_error(response)
    print("Saved platform draft.")


def _save_runtime(settings: Settings, payload: dict[str, Any], version: int | None) -> None:
    from admin_client.generated.models.platform_runtime_policy import (
        PlatformRuntimePolicy,
    )

    with _client(settings) as client:
        response = save_runtime_admin_v1_platform_components_runtime_draft_put.sync_detailed(
            client=client,
            body=RuntimeDraftWrite(policy=PlatformRuntimePolicy.from_dict(payload)),
            if_match=None if version is None else f'"{version}"',
        )
        _response_error(response)
    print("Saved platform runtime draft.")


def _publish(settings: Settings) -> None:
    with _client(settings) as client:
        state = _state(client)
        profiles = PlatformPublishRequestProfilePromptVersions()
        for key, draft in state.profile_prompt_drafts.additional_properties.items():
            profiles[key] = draft.version
        body = PlatformPublishRequest(
            runtime_version=None if state.runtime_draft is None else state.runtime_draft.version,
            system_prompt_version=None if state.system_prompt_draft is None else state.system_prompt_draft.version,
            profile_prompt_versions=profiles,
        )
        response = publish_admin_v1_platform_components_publish_post.sync_detailed(client=client, body=body)
        _response_error(response)
        if response.parsed is None:
            raise CommandError("unexpected client failure: invalid platform release", 1)
        print(f"Published platform release {response.parsed.release_number}.")


def run_system_prompt(settings: Settings, action: str, *, force: bool = False) -> None:
    path = settings.state_dir / "platform" / "system_prompt.md"
    if action == "show":
        with _client(settings) as client:
            state = _state(client)
            print(state.active_system_prompt or "No active system prompt.")
        return
    if action == "pull":
        text = _read(path, required=False)
        if text is not None and not force:
            raise CommandError(f"refusing to overwrite existing file: {path}", 2)
        with _client(settings) as client:
            value = _state(client).active_system_prompt
        if value is None:
            raise CommandError("no active system prompt", 5)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + ("" if value.endswith("\n") else "\n"), encoding="utf-8")
        return
    if action in {"push", "plan"}:
        value = _read(path)
        if action == "plan":
            print(f"system-prompt: {'ready' if value is not None else 'missing-local'}")
            return
        with _client(settings) as client:
            draft = _state(client).system_prompt_draft
        _save_prompt(settings, None, value or "", None if draft is None else draft.version)
        return
    if action == "publish":
        _publish(settings)
        return
    if action == "revisions":
        run_system_prompt(settings, "show")
        return
    raise CommandError(f"unsupported system-prompt action: {action}", 2)


def run_profile(settings: Settings, action: str, profile: str | None, *, force: bool = False) -> None:
    if action == "list":
        with _client(settings) as client:
            state = _state(client)
            print("\n".join(sorted(set(state.active_profile_prompts.additional_properties) | set(state.profile_prompt_drafts.additional_properties))))
        return
    if profile is None:
        raise CommandError("profile key is required", 2)
    path = settings.state_dir / "platform" / "profiles" / f"{profile}.md"
    if action == "show":
        with _client(settings) as client:
            value = _state(client).active_profile_prompts.additional_properties.get(profile)
        print(value or "No active profile prompt.")
        return
    if action == "pull":
        with _client(settings) as client:
            value = _state(client).active_profile_prompts.additional_properties.get(profile)
        if value is None:
            raise CommandError(f"no active profile prompt: {profile}", 5)
        if path.exists() and not force:
            raise CommandError(f"refusing to overwrite existing file: {path}", 2)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + ("" if value.endswith("\n") else "\n"), encoding="utf-8")
        return
    if action in {"push", "plan"}:
        value = _read(path)
        if action == "plan":
            print(f"profile {profile}: {'ready' if value is not None else 'missing-local'}")
            return
        with _client(settings) as client:
            draft = _state(client).profile_prompt_drafts.additional_properties.get(profile)
        _save_prompt(settings, profile, value or "", None if draft is None else draft.version)
        return
    if action == "publish":
        _publish(settings)
        return
    if action == "revisions":
        run_profile(settings, "show", profile)
        return
    if action == "create":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        print(f"Created authoring file {path}")
        return
    raise CommandError(f"unsupported profile action: {action}", 2)


def run_platform_runtime(settings: Settings, action: str, *, force: bool = False) -> None:
    path = settings.state_dir / "platform" / "runtime.yaml"
    if action in {"show", "revisions"}:
        with _client(settings) as client:
            state = _state(client)
            print(yaml.safe_dump(state.active_runtime.to_dict() if state.active_runtime else {}, sort_keys=False))
        return
    if action == "pull":
        with _client(settings) as client:
            state = _state(client)
            value = {} if state.active_runtime is None else state.active_runtime.to_dict()
        if path.exists() and not force:
            raise CommandError(f"refusing to overwrite existing file: {path}", 2)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        return
    if action == "plan":
        print(f"runtime: {'ready' if path.exists() else 'missing-local'}")
        return
    if action == "push":
        try:
            payload = yaml.safe_load(_read(path) or "{}")
        except yaml.YAMLError as error:
            raise CommandError(f"invalid platform runtime YAML: {error}", 2) from error
        if not isinstance(payload, dict):
            raise CommandError("platform runtime YAML root must be a mapping", 2)
        with _client(settings) as client:
            draft = _state(client).runtime_draft
        _save_runtime(settings, payload, None if draft is None else draft.version)
        return
    if action == "publish":
        _publish(settings)
        return
    raise CommandError(f"unsupported runtime action: {action}", 2)
