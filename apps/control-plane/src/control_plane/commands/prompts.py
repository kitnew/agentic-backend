from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

import httpx
from admin_client import AuthenticatedClient
from admin_client.generated.api.adminplatform_prompts import (
    create_profile_prompt_draft_admin_v1_platform_prompts_profiles_drafts_post,
    create_system_prompt_draft_admin_v1_platform_prompts_system_drafts_post,
    list_profile_prompt_revisions_admin_v1_platform_prompts_profiles_key_revisions_get,
    list_profiles_admin_v1_platform_prompts_profiles_get,
    list_system_prompt_revisions_admin_v1_platform_prompts_system_key_revisions_get,
    publish_profile_prompt_draft_admin_v1_platform_prompts_profiles_drafts_revision_id_publish_post,
    publish_system_prompt_draft_admin_v1_platform_prompts_system_drafts_revision_id_publish_post,
    update_profile_prompt_draft_admin_v1_platform_prompts_profiles_drafts_revision_id_patch,
    update_system_prompt_draft_admin_v1_platform_prompts_system_drafts_revision_id_patch,
)
from admin_client.generated.api.admintenants import (
    create_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_post,
    get_tenant_by_slug_admin_v1_tenants_by_slug_slug_get,
    list_tenant_prompt_revisions_admin_v1_tenants_tenant_id_tenant_prompt_revisions_get,
    publish_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_revision_id_publish_post,
    update_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_revision_id_patch,
)
from admin_client.generated.models.create_platform_prompt_draft_request import (
    CreatePlatformPromptDraftRequest,
)
from admin_client.generated.models.create_text_draft_request import (
    CreateTextDraftRequest,
)
from admin_client.generated.models.platform_prompt_publish_response import (
    PlatformPromptPublishResponse,
)
from admin_client.generated.models.platform_prompt_revision_response import (
    PlatformPromptRevisionResponse,
)
from admin_client.generated.models.prompt_text_revision_response import (
    PromptTextRevisionResponse,
)
from admin_client.generated.models.tenant_prompt_revision_response import (
    TenantPromptRevisionResponse,
)
from admin_client.generated.models.tenant_response import TenantResponse
from admin_client.generated.models.update_text_draft_request import (
    UpdateTextDraftRequest,
)
from admin_client.generated.types import Response

from control_plane.settings import Settings

SYSTEM_PROMPT_KEY = "default"
PROFILE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
TENANT_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class PromptCommandError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 5) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class PromptTarget:
    label: str
    key: str
    path: Path
    profile: bool


class PromptRevision(Protocol):
    id: UUID
    revision_number: int
    status: str
    text: str
    created_at: datetime
    published_at: datetime | None
    version: int


@dataclass(frozen=True)
class RemoteState:
    revisions: list[PromptRevision]
    published: PromptRevision | None
    draft: PromptRevision | None


def system_prompt_path(state_dir: Path) -> Path:
    return state_dir / "platform" / "system_prompt.md"


def profile_prompt_path(state_dir: Path, key: str) -> Path:
    if not PROFILE_KEY.fullmatch(key):
        raise PromptCommandError(
            "profile key must match ^[a-z][a-z0-9_]*$", exit_code=2
        )
    return state_dir / "platform" / "profiles" / f"{key}.md"


def tenant_prompt_path(state_dir: Path, slug: str) -> Path:
    if not 3 <= len(slug) <= 63 or not TENANT_SLUG.fullmatch(slug):
        raise PromptCommandError(
            "tenant slug must be 3-63 lowercase letters, digits, or single hyphens",
            exit_code=2,
        )
    return state_dir / "tenants" / slug / "tenant_prompt.md"


def comparable_content(value: str) -> str:
    if value.endswith("\r\n"):
        return value[:-2]
    if value.endswith("\n"):
        return value[:-1]
    return value


def content_matches(left: str, right: str) -> bool:
    return comparable_content(left) == comparable_content(right)


def _detail(content: bytes) -> str:
    try:
        payload = json.loads(content)
        detail = (
            payload.get("detail", payload) if isinstance(payload, dict) else payload
        )
        value = (
            detail
            if isinstance(detail, str)
            else json.dumps(detail, ensure_ascii=False)
        )
    except UnicodeDecodeError, ValueError:
        value = content.decode(errors="replace")
    return value.strip()[:500] or "empty response"


def _response_error(response: Response[Any]) -> None:
    if response.status_code in {401, 403}:
        raise PromptCommandError(
            f"authentication/authorization failed ({response.status_code})", 4
        )
    if response.status_code == 412:
        raise PromptCommandError(
            "remote draft changed; run plan and retry instead of overwriting it"
        )
    if response.status_code == 409:
        raise PromptCommandError("remote prompt state changed; run plan and retry")
    if response.status_code >= 400:
        raise PromptCommandError(
            f"Backend API error ({response.status_code}): {_detail(response.content)}"
        )


def _expect_revisions(response: Response[Any]) -> list[PromptTextRevisionResponse]:
    _response_error(response)
    if not isinstance(response.parsed, list) or not all(
        isinstance(item, PromptTextRevisionResponse) for item in response.parsed
    ):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def _expect_tenant_revisions(
    response: Response[Any],
) -> list[TenantPromptRevisionResponse]:
    _response_error(response)
    if not isinstance(response.parsed, list) or not all(
        isinstance(item, TenantPromptRevisionResponse) for item in response.parsed
    ):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def _expect_revision(
    response: Response[Any],
    expected: type[
        PromptTextRevisionResponse
        | PlatformPromptRevisionResponse
        | TenantPromptRevisionResponse
    ],
) -> (
    PromptTextRevisionResponse
    | PlatformPromptRevisionResponse
    | TenantPromptRevisionResponse
):
    _response_error(response)
    if not isinstance(response.parsed, expected):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def _client(settings: Settings) -> AuthenticatedClient:
    return AuthenticatedClient(
        base_url=settings.api_url,
        token=settings.token,
        timeout=httpx.Timeout(10.0),
    )


def _target(settings: Settings, key: str | None = None) -> PromptTarget:
    if key is None:
        return PromptTarget(
            label="System Prompt",
            key=SYSTEM_PROMPT_KEY,
            path=system_prompt_path(settings.state_dir),
            profile=False,
        )
    return PromptTarget(
        label="Profile Prompt",
        key=key,
        path=profile_prompt_path(settings.state_dir, key),
        profile=True,
    )


def _state(client: AuthenticatedClient, target: PromptTarget) -> RemoteState:
    if target.profile:
        response = list_profile_prompt_revisions_admin_v1_platform_prompts_profiles_key_revisions_get.sync_detailed(
            target.key, client=client
        )
    else:
        response = list_system_prompt_revisions_admin_v1_platform_prompts_system_key_revisions_get.sync_detailed(
            target.key, client=client
        )
    return _remote_state(_expect_revisions(response))


def _remote_state(revisions: Sequence[PromptRevision]) -> RemoteState:
    published = max(
        (item for item in revisions if item.status == "published"),
        key=lambda item: item.revision_number,
        default=None,
    )
    draft = max(
        (item for item in revisions if item.status == "draft"),
        key=lambda item: item.revision_number,
        default=None,
    )
    return RemoteState(list(revisions), published, draft)


def _tenant(client: AuthenticatedClient, slug: str) -> TenantResponse:
    response = get_tenant_by_slug_admin_v1_tenants_by_slug_slug_get.sync_detailed(
        slug, client=client
    )
    if response.status_code == 404:
        raise PromptCommandError(f"unknown tenant: {slug}")
    _response_error(response)
    if not isinstance(response.parsed, TenantResponse):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    if response.parsed.slug != slug:
        raise PromptCommandError("unexpected client failure: tenant slug mismatch", 1)
    return response.parsed


def _tenant_state(client: AuthenticatedClient, tenant_id: UUID) -> RemoteState:
    response = list_tenant_prompt_revisions_admin_v1_tenants_tenant_id_tenant_prompt_revisions_get.sync_detailed(
        tenant_id, client=client
    )
    revisions: list[PromptRevision] = list(_expect_tenant_revisions(response))
    return _remote_state(revisions)


def _profiles(client: AuthenticatedClient) -> list[str]:
    response = list_profiles_admin_v1_platform_prompts_profiles_get.sync_detailed(
        client=client
    )
    _response_error(response)
    if not isinstance(response.parsed, list) or not all(
        isinstance(item, str) for item in response.parsed
    ):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def _ensure_profile(client: AuthenticatedClient, key: str) -> None:
    if key not in _profiles(client):
        raise PromptCommandError(f"unknown profile: {key}", 5)


def _read(path: Path, *, required: bool) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        if not required:
            return None
        raise PromptCommandError(f"missing canonical prompt file: {path}", 2) from None
    except (OSError, UnicodeDecodeError) as error:
        raise PromptCommandError(
            f"cannot read canonical prompt file {path}: {error}", 2
        ) from error


def _show(target: PromptTarget, state: RemoteState) -> None:
    if not state.revisions:
        raise PromptCommandError(f"{target.label} '{target.key}' does not exist")
    print(f"{target.label}: {target.key}")
    if state.published is None:
        print("published revision: none")
    else:
        print(f"published revision: {state.published.revision_number}")
        print(f"published status: {state.published.status}")
    if state.draft is None:
        print("draft revision: none")
    else:
        print(f"draft revision: {state.draft.revision_number}")
        print(f"draft status: {state.draft.status}")
        print(f"draft version: {state.draft.version}")


def _revisions(target: PromptTarget, state: RemoteState) -> None:
    if not state.revisions:
        print("No revisions.")
        return
    print("REVISION\tSTATUS\tCREATED/PUBLISHED")
    for revision in state.revisions:
        timestamp = revision.published_at or revision.created_at
        print(f"{revision.revision_number}\t{revision.status}\t{timestamp.isoformat()}")


def _pull(target: PromptTarget, state: RemoteState, *, force: bool) -> None:
    if state.published is None:
        raise PromptCommandError(
            f"{target.label} '{target.key}' has no published revision"
        )
    local = _read(target.path, required=False)
    if local is not None and content_matches(local, state.published.text):
        print(f"Already current: {target.path}")
        return
    if local is not None and not force:
        raise PromptCommandError(
            "Local file differs from remote published revision. Use --force to overwrite it.",
            2,
        )
    try:
        target.path.parent.mkdir(parents=True, exist_ok=True)
        target.path.write_bytes(state.published.text.encode("utf-8"))
    except OSError as error:
        raise PromptCommandError(
            f"cannot write canonical prompt file {target.path}: {error}", 2
        ) from error
    print(
        f"Wrote published revision {state.published.revision_number} to {target.path}"
    )


def _plan(target: PromptTarget, state: RemoteState) -> None:
    local = _read(target.path, required=False)
    print(f"{target.label}: {target.key}\n")
    if local is None:
        local_status = "missing-local"
    elif not state.revisions:
        local_status = "local-only"
    elif state.draft is not None and not content_matches(local, state.draft.text):
        local_status = "draft-conflict"
    elif state.draft is not None or (
        state.published is not None and content_matches(local, state.published.text)
    ):
        local_status = "unchanged"
    else:
        local_status = "modified"
    print(f"Status: {local_status}\n")
    print("Local:")
    print(f"  {target.path}\n")
    print("Remote:")
    print(
        "  published revision: "
        + (str(state.published.revision_number) if state.published else "none")
    )
    print(
        "  draft revision: "
        + (str(state.draft.revision_number) if state.draft else "none")
    )
    if state.draft is not None:
        print(f"  draft version: {state.draft.version}")
    print("\nPlan:")
    if local is None:
        print("  no mutation; create the canonical file or run pull")
    elif local_status == "unchanged":
        print("  no changes")
    elif state.draft is not None:
        print(f"  update existing draft revision {state.draft.revision_number}")
        print("  no publication")
    else:
        print("  create draft revision")
        print("  no publication")


def _push(
    client: AuthenticatedClient, target: PromptTarget, state: RemoteState
) -> None:
    local = _read(target.path, required=True)
    assert local is not None
    if state.draft is not None and content_matches(local, state.draft.text):
        print(f"No changes; draft revision {state.draft.revision_number} is current.")
        return
    if (
        state.draft is None
        and state.published is not None
        and content_matches(local, state.published.text)
    ):
        print(
            f"No changes; published revision {state.published.revision_number} is current."
        )
        return
    if state.draft is None:
        create_body = CreatePlatformPromptDraftRequest(key=target.key, text=local)
        create_response = (
            create_profile_prompt_draft_admin_v1_platform_prompts_profiles_drafts_post.sync_detailed(
                client=client, body=create_body
            )
            if target.profile
            else create_system_prompt_draft_admin_v1_platform_prompts_system_drafts_post.sync_detailed(
                client=client, body=create_body
            )
        )
        revision = _expect_revision(create_response, PlatformPromptRevisionResponse)
    else:
        update_body = UpdateTextDraftRequest(text=local)
        if_match = f'"{state.draft.version}"'
        update_response = (
            update_profile_prompt_draft_admin_v1_platform_prompts_profiles_drafts_revision_id_patch.sync_detailed(
                state.draft.id,
                client=client,
                body=update_body,
                if_match=if_match,
            )
            if target.profile
            else update_system_prompt_draft_admin_v1_platform_prompts_system_drafts_revision_id_patch.sync_detailed(
                state.draft.id,
                client=client,
                body=update_body,
                if_match=if_match,
            )
        )
        revision = _expect_revision(update_response, PromptTextRevisionResponse)
    print(f"Draft revision {revision.revision_number}, version {revision.version}")


def _publish(
    client: AuthenticatedClient, target: PromptTarget, state: RemoteState
) -> None:
    if state.draft is None:
        raise PromptCommandError(
            f"{target.label} '{target.key}' has no draft to publish"
        )
    response = (
        publish_profile_prompt_draft_admin_v1_platform_prompts_profiles_drafts_revision_id_publish_post.sync_detailed(
            state.draft.id, client=client
        )
        if target.profile
        else publish_system_prompt_draft_admin_v1_platform_prompts_system_drafts_revision_id_publish_post.sync_detailed(
            state.draft.id, client=client
        )
    )
    _response_error(response)
    if not isinstance(
        response.parsed, (PlatformPromptPublishResponse, PromptTextRevisionResponse)
    ):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    revision = response.parsed
    print(
        f"Published {target.label} '{target.key}' revision {revision.revision_number}"
    )
    if isinstance(revision, PlatformPromptPublishResponse):
        print(
            "PromptSet rollout: "
            f"updated tenants: {revision.rollout.updated_tenants}, "
            f"unchanged tenants: {revision.rollout.unchanged_tenants}"
        )


def _push_tenant_prompt(
    client: AuthenticatedClient,
    tenant: TenantResponse,
    target: PromptTarget,
    state: RemoteState,
) -> None:
    local = _read(target.path, required=True)
    assert local is not None
    if state.draft is not None and content_matches(local, state.draft.text):
        print(f"No changes; draft revision {state.draft.revision_number} is current.")
        return
    if (
        state.draft is None
        and state.published is not None
        and content_matches(local, state.published.text)
    ):
        print(
            f"No changes; published revision {state.published.revision_number} is current."
        )
        return
    if state.draft is None:
        response = create_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_post.sync_detailed(
            tenant.id,
            client=client,
            body=CreateTextDraftRequest(text=local),
        )
    else:
        response = update_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_revision_id_patch.sync_detailed(
            tenant.id,
            state.draft.id,
            client=client,
            body=UpdateTextDraftRequest(text=local),
            if_match=f'"{state.draft.version}"',
        )
    revision = _expect_revision(response, TenantPromptRevisionResponse)
    print(f"Draft revision {revision.revision_number}, version {revision.version}")


def _publish_tenant_prompt(
    client: AuthenticatedClient,
    tenant: TenantResponse,
    target: PromptTarget,
    state: RemoteState,
) -> None:
    if state.draft is None:
        raise PromptCommandError(
            f"{target.label} '{target.key}' has no draft to publish"
        )
    response = publish_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_revision_id_publish_post.sync_detailed(
        tenant.id, state.draft.id, client=client
    )
    revision = _expect_revision(response, TenantPromptRevisionResponse)
    print(
        f"Published Tenant Prompt for '{tenant.slug}' revision "
        f"{revision.revision_number}."
    )
    print(
        "This revision is not active in runtime until a published PromptSet "
        "references it."
    )


def _create_profile(client: AuthenticatedClient, target: PromptTarget) -> None:
    if target.key in _profiles(client):
        raise PromptCommandError(f"profile already exists: {target.key}")
    local = _read(target.path, required=True)
    assert local is not None
    response = create_profile_prompt_draft_admin_v1_platform_prompts_profiles_drafts_post.sync_detailed(
        client=client,
        body=CreatePlatformPromptDraftRequest(key=target.key, text=local),
    )
    revision = _expect_revision(response, PlatformPromptRevisionResponse)
    print(
        f"Created Profile Prompt '{target.key}' draft revision "
        f"{revision.revision_number}, version {revision.version}"
    )


def run_system_prompt(settings: Settings, action: str, *, force: bool = False) -> None:
    target = _target(settings)
    with _client(settings) as client:
        state = _state(client, target)
        _run_action(client, target, state, action, force=force)


def run_profile(
    settings: Settings,
    action: str,
    key: str | None = None,
    *,
    force: bool = False,
) -> None:
    with _client(settings) as client:
        if action == "list":
            profiles = _profiles(client)
            if not profiles:
                print("No profiles.")
            else:
                print("\n".join(profiles))
            return
        assert key is not None
        target = _target(settings, key)
        if action == "create":
            _create_profile(client, target)
            return
        _ensure_profile(client, key)
        state = _state(client, target)
        _run_action(client, target, state, action, force=force)


def run_tenant_prompt(
    settings: Settings,
    action: str,
    slug: str,
    *,
    force: bool = False,
) -> None:
    target = PromptTarget(
        label="Tenant Prompt",
        key=slug,
        path=tenant_prompt_path(settings.state_dir, slug),
        profile=False,
    )
    with _client(settings) as client:
        tenant = _tenant(client, slug)
        state = _tenant_state(client, tenant.id)
        if action == "push":
            _push_tenant_prompt(client, tenant, target, state)
        elif action == "publish":
            _publish_tenant_prompt(client, tenant, target, state)
        else:
            _run_action(client, target, state, action, force=force)


def _run_action(
    client: AuthenticatedClient,
    target: PromptTarget,
    state: RemoteState,
    action: str,
    *,
    force: bool,
) -> None:
    if action == "show":
        _show(target, state)
    elif action == "revisions":
        _revisions(target, state)
    elif action == "pull":
        _pull(target, state, force=force)
    elif action == "plan":
        _plan(target, state)
    elif action == "push":
        _push(client, target, state)
    elif action == "publish":
        _publish(client, target, state)
    else:
        raise PromptCommandError(f"unsupported prompt action: {action}", 2)
