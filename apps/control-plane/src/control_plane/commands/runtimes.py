from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from admin_client import AuthenticatedClient
from admin_client.generated.api.adminplatform_runtime import (
    create_platform_runtime_draft_admin_v1_platform_runtime_drafts_post,
    list_platform_runtime_revisions_admin_v1_platform_runtime_revisions_get,
    publish_platform_runtime_draft_admin_v1_platform_runtime_drafts_revision_id_publish_post,
    show_platform_runtime_admin_v1_platform_runtime_get,
    update_platform_runtime_draft_admin_v1_platform_runtime_drafts_revision_id_patch,
    validate_platform_runtime_admin_v1_platform_runtime_validate_post,
)
from admin_client.generated.api.admintenant_runtime import (
    create_tenant_runtime_draft_admin_v1_tenants_tenant_id_runtime_drafts_post,
    list_tenant_runtime_revisions_admin_v1_tenants_tenant_id_runtime_revisions_get,
    publish_tenant_runtime_draft_admin_v1_tenants_tenant_id_runtime_drafts_revision_id_publish_post,
    show_tenant_runtime_admin_v1_tenants_tenant_id_runtime_get,
    update_tenant_runtime_draft_admin_v1_tenants_tenant_id_runtime_drafts_revision_id_patch,
    validate_tenant_runtime_admin_v1_tenants_tenant_id_runtime_validate_post,
)
from admin_client.generated.models.platform_runtime_request import (
    PlatformRuntimeRequest,
)
from admin_client.generated.models.platform_runtime_revision_response import (
    PlatformRuntimeRevisionResponse,
)
from admin_client.generated.models.platform_runtime_state_response import (
    PlatformRuntimeStateResponse,
)
from admin_client.generated.models.runtime_validation_response import (
    RuntimeValidationResponse,
)
from admin_client.generated.models.tenant_runtime_request import TenantRuntimeRequest
from admin_client.generated.models.tenant_runtime_revision_response import (
    TenantRuntimeRevisionResponse,
)
from admin_client.generated.models.tenant_runtime_state_response import (
    TenantRuntimeStateResponse,
)
from admin_client.generated.types import Response

from control_plane.commands.prompts import (
    PromptCommandError,
    _client,
    _response_error,
    _tenant,
    tenant_prompt_path,
)
from control_plane.commands.tenant_configs import _write
from control_plane.settings import Settings


def platform_runtime_path(state_dir: Path) -> Path:
    return state_dir / "platform" / "runtime.yaml"


def tenant_runtime_path(state_dir: Path, slug: str) -> Path:
    return tenant_prompt_path(state_dir, slug).with_name("runtime.yaml")


def parse_runtime_yaml(text: str, *, platform: bool) -> dict[str, Any]:
    label = "PlatformRuntime" if platform else "TenantRuntime"
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError as error:
        raise PromptCommandError(f"invalid {label} YAML: {error}", 2) from error
    if len(documents) != 1:
        raise PromptCommandError(f"{label} YAML must contain exactly one document", 2)
    document = documents[0]
    if not isinstance(document, dict):
        raise PromptCommandError(f"{label} YAML root must be a mapping", 2)
    _require_json(document, label)
    return document


def _require_json(value: object, label: str, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PromptCommandError(
                    f"{label} YAML mapping key at {path or '<root>'} must be a string",
                    2,
                )
            _require_json(item, label, f"{path}.{key}".strip("."))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _require_json(item, label, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise PromptCommandError(
            f"{label} YAML value at {path or '<root>'} must be finite", 2
        )
    elif value is not None and not isinstance(value, str | int | float | bool):
        raise PromptCommandError(
            f"{label} YAML value at {path or '<root>'} must be JSON-compatible",
            2,
        )


def serialize_runtime_yaml(settings: dict[str, Any]) -> str:
    return yaml.safe_dump(
        settings,
        allow_unicode=True,
        default_flow_style=False,
        indent=2,
        sort_keys=False,
    )


def read_runtime(
    path: Path, *, platform: bool, required: bool = True
) -> dict[str, Any] | None:
    try:
        return parse_runtime_yaml(path.read_text(encoding="utf-8"), platform=platform)
    except FileNotFoundError:
        if not required:
            return None
        raise PromptCommandError(f"missing canonical runtime file: {path}", 2) from None
    except (OSError, UnicodeDecodeError) as error:
        raise PromptCommandError(
            f"cannot read canonical runtime file {path}: {error}", 2
        ) from error


def _expect(response: Response[Any], expected: type[Any]) -> Any:
    _response_error(response)
    if not isinstance(response.parsed, expected):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def _platform_request(policy: dict[str, Any]) -> PlatformRuntimeRequest:
    try:
        return PlatformRuntimeRequest.from_dict({"policy": policy})
    except (KeyError, TypeError, ValueError) as error:
        raise PromptCommandError(
            f"invalid PlatformRuntime shape: {error}", 2
        ) from error


def _tenant_request(settings: dict[str, Any]) -> TenantRuntimeRequest:
    try:
        return TenantRuntimeRequest.from_dict({"settings": settings})
    except (KeyError, TypeError, ValueError) as error:
        raise PromptCommandError(f"invalid TenantRuntime shape: {error}", 2) from error


def validate_platform(client: AuthenticatedClient, policy: dict[str, Any]) -> None:
    response = (
        validate_platform_runtime_admin_v1_platform_runtime_validate_post.sync_detailed(
            client=client, body=_platform_request(policy)
        )
    )
    _expect(response, RuntimeValidationResponse)


def validate_tenant(
    client: AuthenticatedClient, tenant_id: UUID, settings: dict[str, Any]
) -> None:
    response = validate_tenant_runtime_admin_v1_tenants_tenant_id_runtime_validate_post.sync_detailed(
        tenant_id, client=client, body=_tenant_request(settings)
    )
    _expect(response, RuntimeValidationResponse)


def platform_state(client: AuthenticatedClient) -> PlatformRuntimeStateResponse:
    response = show_platform_runtime_admin_v1_platform_runtime_get.sync_detailed(
        client=client
    )
    return _expect(response, PlatformRuntimeStateResponse)


def tenant_state(
    client: AuthenticatedClient, tenant_id: UUID
) -> TenantRuntimeStateResponse:
    response = show_tenant_runtime_admin_v1_tenants_tenant_id_runtime_get.sync_detailed(
        tenant_id, client=client
    )
    return _expect(response, TenantRuntimeStateResponse)


def _platform_value(revision: PlatformRuntimeRevisionResponse) -> dict[str, Any]:
    return _without_none(revision.policy.to_dict())


def _tenant_value(revision: TenantRuntimeRevisionResponse) -> dict[str, Any]:
    return _without_none(revision.settings.to_dict())


def _without_none(value: object) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_none(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_without_none(item) for item in value]
    return value


def _comparison(
    state: PlatformRuntimeStateResponse | TenantRuntimeStateResponse,
) -> object:
    revision = state.draft_revision or state.latest_published_revision
    if isinstance(revision, PlatformRuntimeRevisionResponse):
        return _platform_value(revision)
    if isinstance(revision, TenantRuntimeRevisionResponse):
        return _tenant_value(revision)
    return None


def plan_status(local: dict[str, Any], state: object) -> str:
    comparison = _comparison(state)  # type: ignore[arg-type]
    if comparison is None:
        return "local-only"
    return "unchanged" if local == comparison else "modified"


def push_platform(
    client: AuthenticatedClient, policy: dict[str, Any]
) -> tuple[PlatformRuntimeRevisionResponse, bool]:
    validate_platform(client, policy)
    state = platform_state(client)
    if policy == _comparison(state):
        revision = state.draft_revision or state.latest_published_revision
        assert isinstance(revision, PlatformRuntimeRevisionResponse)
        return revision, False
    if state.draft_revision is None:
        response = create_platform_runtime_draft_admin_v1_platform_runtime_drafts_post.sync_detailed(
            client=client, body=_platform_request(policy)
        )
    else:
        response = update_platform_runtime_draft_admin_v1_platform_runtime_drafts_revision_id_patch.sync_detailed(
            state.draft_revision.id,
            client=client,
            body=_platform_request(policy),
            if_match=f'"{state.draft_revision.version}"',
        )
    return _expect(response, PlatformRuntimeRevisionResponse), True


def push_tenant(
    client: AuthenticatedClient,
    tenant_id: UUID,
    settings: dict[str, Any],
) -> tuple[TenantRuntimeRevisionResponse, bool]:
    validate_tenant(client, tenant_id, settings)
    state = tenant_state(client, tenant_id)
    if settings == _comparison(state):
        revision = state.draft_revision or state.latest_published_revision
        assert isinstance(revision, TenantRuntimeRevisionResponse)
        return revision, False
    if state.draft_revision is None:
        response = create_tenant_runtime_draft_admin_v1_tenants_tenant_id_runtime_drafts_post.sync_detailed(
            tenant_id, client=client, body=_tenant_request(settings)
        )
    else:
        response = update_tenant_runtime_draft_admin_v1_tenants_tenant_id_runtime_drafts_revision_id_patch.sync_detailed(
            tenant_id,
            state.draft_revision.id,
            client=client,
            body=_tenant_request(settings),
            if_match=f'"{state.draft_revision.version}"',
        )
    return _expect(response, TenantRuntimeRevisionResponse), True


def publish_platform(
    client: AuthenticatedClient, state: PlatformRuntimeStateResponse
) -> PlatformRuntimeRevisionResponse:
    if state.draft_revision is None:
        raise PromptCommandError("Platform Runtime has no draft to publish", 5)
    response = publish_platform_runtime_draft_admin_v1_platform_runtime_drafts_revision_id_publish_post.sync_detailed(
        state.draft_revision.id, client=client
    )
    return _expect(response, PlatformRuntimeRevisionResponse)


def publish_tenant(
    client: AuthenticatedClient,
    tenant_id: UUID,
    state: TenantRuntimeStateResponse,
) -> TenantRuntimeRevisionResponse:
    if state.draft_revision is None:
        raise PromptCommandError("Tenant Runtime has no draft to publish", 5)
    response = publish_tenant_runtime_draft_admin_v1_tenants_tenant_id_runtime_drafts_revision_id_publish_post.sync_detailed(
        tenant_id, state.draft_revision.id, client=client
    )
    return _expect(response, TenantRuntimeRevisionResponse)


def _print_state(
    label: str, state: PlatformRuntimeStateResponse | TenantRuntimeStateResponse
) -> None:
    print(f"{label}\n")
    print(
        "Published revision: "
        + (
            "none"
            if state.latest_published_revision is None
            else str(state.latest_published_revision.revision_number)
        )
    )
    print(
        "Draft revision: "
        + (
            "none"
            if state.draft_revision is None
            else str(state.draft_revision.revision_number)
        )
    )
    revision = state.draft_revision or state.latest_published_revision
    if isinstance(revision, PlatformRuntimeRevisionResponse):
        print("\n" + serialize_runtime_yaml(_platform_value(revision)), end="")
    elif isinstance(revision, TenantRuntimeRevisionResponse):
        print("\n" + serialize_runtime_yaml(_tenant_value(revision)), end="")


def _print_revisions(revisions: list[Any]) -> None:
    if not revisions:
        print("No runtime revisions.")
        return
    print("REVISION  STATUS      VERSION  PUBLISHED")
    for revision in revisions:
        published = (
            "-" if revision.published_at is None else revision.published_at.isoformat()
        )
        print(
            f"{revision.revision_number:<8}  {revision.status.value:<10}  "
            f"{revision.version:<7}  {published}"
        )


def run_platform_runtime(
    settings: Settings, action: str, *, force: bool = False
) -> None:
    path = platform_runtime_path(settings.state_dir)
    with _client(settings) as client:
        if action == "show":
            _print_state("Platform Runtime", platform_state(client))
        elif action == "revisions":
            response = list_platform_runtime_revisions_admin_v1_platform_runtime_revisions_get.sync_detailed(
                client=client
            )
            _response_error(response)
            if not isinstance(response.parsed, list) or not all(
                isinstance(item, PlatformRuntimeRevisionResponse)
                for item in response.parsed
            ):
                raise PromptCommandError(
                    "unexpected client failure: invalid Backend response", 1
                )
            _print_revisions(response.parsed)
        elif action == "plan":
            local = read_runtime(path, platform=True)
            assert local is not None
            validate_platform(client, local)
            state = platform_state(client)
            shown = plan_status(local, state)
            print(f"Platform Runtime Plan\n\nStatus: {shown}\n")
            print(
                "Plan: "
                + ("no changes" if shown == "unchanged" else "create or update draft")
            )
        elif action == "push":
            local = read_runtime(path, platform=True)
            assert local is not None
            revision, changed = push_platform(client, local)
            print(
                f"Platform Runtime revision {revision.revision_number}: "
                + ("draft updated" if changed else "unchanged")
            )
        elif action == "publish":
            revision = publish_platform(client, platform_state(client))
            print(f"Published Platform Runtime revision {revision.revision_number}.")
            print("Tenant VoiceRuntime revisions were not changed.")
        elif action == "pull":
            state = platform_state(client)
            if state.latest_published_revision is None:
                raise PromptCommandError(
                    "Platform Runtime has no published revision", 5
                )
            content = serialize_runtime_yaml(
                _platform_value(state.latest_published_revision)
            )
            if (
                path.exists()
                and not force
                and path.read_text(encoding="utf-8") != content
            ):
                raise PromptCommandError(
                    "local runtime differs; use --force to overwrite", 2
                )
            _write(path, content)
            print(f"Pulled Platform Runtime to {path}.")
        else:
            raise PromptCommandError(f"unsupported runtime action: {action}", 2)


def run_tenant_runtime(
    settings: Settings, action: str, slug: str, *, force: bool = False
) -> None:
    path = tenant_runtime_path(settings.state_dir, slug)
    with _client(settings) as client:
        tenant = _tenant(client, slug)
        if action == "show":
            _print_state(f"Tenant Runtime: {slug}", tenant_state(client, tenant.id))
        elif action == "revisions":
            response = list_tenant_runtime_revisions_admin_v1_tenants_tenant_id_runtime_revisions_get.sync_detailed(
                tenant.id, client=client
            )
            _response_error(response)
            if not isinstance(response.parsed, list) or not all(
                isinstance(item, TenantRuntimeRevisionResponse)
                for item in response.parsed
            ):
                raise PromptCommandError(
                    "unexpected client failure: invalid Backend response", 1
                )
            _print_revisions(response.parsed)
        elif action == "plan":
            local = read_runtime(path, platform=False)
            assert local is not None
            validate_tenant(client, tenant.id, local)
            shown = plan_status(local, tenant_state(client, tenant.id))
            print(f"Tenant Runtime Plan: {slug}\n\nStatus: {shown}\n")
            print(
                "Plan: "
                + ("no changes" if shown == "unchanged" else "create or update draft")
            )
        elif action == "push":
            local = read_runtime(path, platform=False)
            assert local is not None
            revision, changed = push_tenant(client, tenant.id, local)
            print(
                f"Tenant Runtime revision {revision.revision_number}: "
                + ("draft updated" if changed else "unchanged")
            )
        elif action == "publish":
            revision = publish_tenant(
                client, tenant.id, tenant_state(client, tenant.id)
            )
            print(f"Published Tenant Runtime revision {revision.revision_number}.")
            print(
                "Active VoiceRuntime was not changed; run tenant voice-runtime apply."
            )
        elif action == "pull":
            state = tenant_state(client, tenant.id)
            if state.latest_published_revision is None:
                raise PromptCommandError("Tenant Runtime has no published revision", 5)
            content = serialize_runtime_yaml(
                _tenant_value(state.latest_published_revision)
            )
            if (
                path.exists()
                and not force
                and path.read_text(encoding="utf-8") != content
            ):
                raise PromptCommandError(
                    "local runtime differs; use --force to overwrite", 2
                )
            _write(path, content)
            print(f"Pulled Tenant Runtime to {path}.")
        else:
            raise PromptCommandError(f"unsupported tenant runtime action: {action}", 2)
