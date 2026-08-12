from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from admin_client import AuthenticatedClient
from admin_client.generated.api.adminintegrations import (
    list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
)
from admin_client.generated.api.admintenants import (
    create_config_draft_admin_v1_tenants_tenant_id_config_drafts_post,
    get_active_config_admin_v1_tenants_tenant_id_config_active_get,
    list_config_revisions_admin_v1_tenants_tenant_id_config_revisions_get,
    publish_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_publish_post,
    update_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_patch,
    validate_config_admin_v1_tenants_tenant_id_config_validate_post,
    validate_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_validate_post,
)
from admin_client.generated.models.active_tenant_config import ActiveTenantConfig
from admin_client.generated.models.config_revision_response import (
    ConfigRevisionResponse,
)
from admin_client.generated.models.config_revision_status import ConfigRevisionStatus
from admin_client.generated.models.create_draft_request import CreateDraftRequest
from admin_client.generated.models.create_draft_request_config_type_0 import (
    CreateDraftRequestConfigType0,
)
from admin_client.generated.models.integration_connection_response import (
    IntegrationConnectionResponse,
)
from admin_client.generated.models.integration_connection_status import (
    IntegrationConnectionStatus,
)
from admin_client.generated.models.integration_provider import IntegrationProvider
from admin_client.generated.models.tenant_response import TenantResponse
from admin_client.generated.models.update_draft_request import UpdateDraftRequest
from admin_client.generated.models.update_draft_request_config_type_0 import (
    UpdateDraftRequestConfigType0,
)
from admin_client.generated.models.validate_config_request import ValidateConfigRequest
from admin_client.generated.models.validate_config_request_config import (
    ValidateConfigRequestConfig,
)
from admin_client.generated.models.validate_config_response import (
    ValidateConfigResponse,
)
from admin_client.generated.models.validate_config_response_normalized_config_type_0 import (
    ValidateConfigResponseNormalizedConfigType0,
)
from admin_client.generated.models.validate_draft_response import ValidateDraftResponse
from admin_client.generated.types import Response, Unset

from control_plane.commands.prompts import (
    PromptCommandError,
    _client,
    _response_error,
    _tenant,
    tenant_prompt_path,
)
from control_plane.settings import Settings

CURRENT_SCHEMA_VERSION = 4
MAX_DIFFS = 20
_POST_CALL_EXECUTION = {
    "plan_type": "managed_webhook.post_json.v1",
    "mapping_language": "jsonata",
    "mapping_contract_version": 1,
    "mapping_engine": "jsonata-python",
    "mapping_engine_version": "0.7.0",
}
_POST_CALL_ACTION_FIELDS = {
    "id",
    "type",
    "connection",
    "inputs",
    "request_mapping",
    "timeout_seconds",
}
_POST_CALL_PRESET_FIELDS = {"id", "connection", "preset"}
_POST_CALL_PRESETS: dict[str, tuple[dict[str, Any], str]] = {
    "transcript.raw_json": (
        {
            "transcript": {
                "artifact": "transcript",
                "representation": "raw_json",
            }
        },
        '{"call_id": call_id, "messages": inputs.transcript.value}',
    ),
    "recording.base64": (
        {
            "recording": {
                "artifact": "call_recording",
                "representation": "base64_text",
            }
        },
        '{"call_id": call_id, "recording": inputs.recording.body}',
    ),
}


@dataclass(frozen=True)
class ConfigState:
    revisions: list[ConfigRevisionResponse]
    active: ActiveTenantConfig | None
    draft: ConfigRevisionResponse | None


@dataclass(frozen=True)
class ConfigDiff:
    path: str
    old: object
    new: object


def tenant_config_path(state_dir: Path, slug: str) -> Path:
    return tenant_prompt_path(state_dir, slug).with_name("tenant.yaml")


def parse_tenant_yaml(text: str) -> dict[str, Any]:
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError as error:
        raise PromptCommandError(f"invalid TenantConfig YAML: {error}", 2) from error
    if len(documents) != 1:
        raise PromptCommandError(
            "TenantConfig YAML must contain exactly one document", 2
        )
    document = documents[0]
    if not isinstance(document, dict):
        raise PromptCommandError("TenantConfig YAML root must be a mapping", 2)
    if not all(isinstance(key, str) for key in document):
        raise PromptCommandError("TenantConfig YAML mapping keys must be strings", 2)
    version = document.get("schema_version")
    if type(version) is not int or version != CURRENT_SCHEMA_VERSION:
        shown = repr(version) if version is not None else "missing"
        raise PromptCommandError(
            f"TenantConfig schema version {shown} is not writable by this client. "
            f"Current authoring schema is version {CURRENT_SCHEMA_VERSION}.",
            2,
        )
    _require_json_values(document)
    return document


def _require_json_values(value: object, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PromptCommandError(
                    f"TenantConfig YAML mapping key at {path or '<root>'} must be a string",
                    2,
                )
            _require_json_values(item, f"{path}.{key}".strip("."))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _require_json_values(item, f"{path}[{index}]")
    elif value is not None and not isinstance(value, str | int | float | bool):
        raise PromptCommandError(
            f"TenantConfig YAML value at {path or '<root>'} must be JSON-compatible",
            2,
        )


def _sorted_free_mapping(value: object) -> object:
    if isinstance(value, dict):
        return {key: _sorted_free_mapping(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted_free_mapping(item) for item in value]
    return value


def canonical_config(config: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(config)
    capabilities = result.get("capabilities")
    if isinstance(capabilities, dict):
        result["capabilities"] = _sorted_free_mapping(capabilities)
    return result


def _connections(
    client: AuthenticatedClient, tenant_id: UUID
) -> list[IntegrationConnectionResponse]:
    response = list_connections_admin_v1_tenants_tenant_id_integration_connections_get.sync_detailed(
        tenant_id, client=client
    )
    _config_response_error(response)
    if not isinstance(response.parsed, list) or not all(
        isinstance(item, IntegrationConnectionResponse) for item in response.parsed
    ):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def _connections_by_key(
    client: AuthenticatedClient, tenant_id: UUID
) -> dict[str, IntegrationConnectionResponse]:
    result: dict[str, IntegrationConnectionResponse] = {}
    for connection in _connections(client, tenant_id):
        if connection.key in result:
            raise PromptCommandError(
                f"ambiguous integration connection: {connection.key}", 1
            )
        result[connection.key] = connection
    return result


def compile_authoring_config(
    client: AuthenticatedClient, tenant_id: UUID, config: Mapping[str, Any]
) -> dict[str, Any]:
    """Compile the small authoring surface into the pinned runtime contract."""
    result = canonical_config(config)
    actions = result.get("post_call_actions")
    if actions is None:
        return result
    if not isinstance(actions, list):
        raise PromptCommandError("post_call_actions must be a list", 2)
    if all(isinstance(action, dict) and "action_id" in action for action in actions):
        return result
    if any(isinstance(action, dict) and "action_id" in action for action in actions):
        raise PromptCommandError(
            "post_call_actions cannot mix authoring actions with runtime actions", 2
        )

    connections = _connections_by_key(client, tenant_id)
    compiled: list[dict[str, Any]] = []
    action_ids: set[str] = set()
    for index, action in enumerate(actions):
        label = f"post_call_actions[{index}]"
        if not isinstance(action, dict):
            raise PromptCommandError(f"{label} must be a mapping", 2)
        preset_name = action.get("preset")
        fields = (
            _POST_CALL_PRESET_FIELDS
            if preset_name is not None
            else _POST_CALL_ACTION_FIELDS
        )
        unknown = set(action) - fields
        if unknown:
            raise PromptCommandError(
                f"{label} has unknown fields: {', '.join(sorted(unknown))}", 2
            )
        action_id = action.get("id")
        if not isinstance(action_id, str) or not action_id:
            raise PromptCommandError(f"{label}.id must be a non-empty string", 2)
        if action_id in action_ids:
            raise PromptCommandError("post_call_actions IDs must be unique", 2)
        action_ids.add(action_id)
        connection = action.get("connection")
        if not isinstance(connection, str) or not connection:
            raise PromptCommandError(
                f"{label}.connection must be a non-empty string", 2
            )
        resolved = connections.get(connection)
        if resolved is None:
            raise PromptCommandError(
                f"{label}.connection references unknown integration connection {connection!r}",
                2,
            )
        if (
            resolved.provider is not IntegrationProvider.MANAGED_WEBHOOK
            or resolved.status is not IntegrationConnectionStatus.ACTIVE
        ):
            raise PromptCommandError(
                f"{label}.connection must reference an active managed_webhook connection",
                2,
            )
        if preset_name is not None:
            if (
                not isinstance(preset_name, str)
                or preset_name not in _POST_CALL_PRESETS
            ):
                raise PromptCommandError(f"{label}.preset is unknown", 2)
            inputs, request_mapping = _POST_CALL_PRESETS[preset_name]
            timeout_seconds = 10
        else:
            if action.get("type") != "http.post_json":
                raise PromptCommandError(f"{label}.type must be http.post_json", 2)
            inputs = action.get("inputs", {})
            custom_mapping = action.get("request_mapping")
            if not isinstance(custom_mapping, str) or not custom_mapping:
                raise PromptCommandError(
                    f"{label}.request_mapping must be a non-empty string", 2
                )
            request_mapping = custom_mapping
            timeout_seconds = action.get("timeout_seconds", 10)
            if type(timeout_seconds) is not int:
                raise PromptCommandError(
                    f"{label}.timeout_seconds must be an integer", 2
                )
        compiled.append(
            {
                "action_id": action_id,
                "type": "http.post_json",
                "inputs": inputs,
                "semantic_key": f"post_call.{action_id}",
                "semantic_version": 1,
                "execution": {
                    **_POST_CALL_EXECUTION,
                    "connection_id": str(resolved.id),
                    "request_mapping": request_mapping,
                    "timeout_seconds": timeout_seconds,
                },
            }
        )
    return canonical_config({**result, "post_call_actions": compiled})


def authoring_config(
    client: AuthenticatedClient, tenant_id: UUID, config: Mapping[str, Any]
) -> dict[str, Any]:
    """Render a pinned runtime config back to its small authoring surface."""
    result = canonical_config(config)
    actions = result.get("post_call_actions")
    if not isinstance(actions, list) or not actions:
        return result
    connections = {str(item.id): item.key for item in _connections(client, tenant_id)}
    authored: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        label = f"post_call_actions[{index}]"
        if not isinstance(action, dict) or not isinstance(
            action.get("execution"), dict
        ):
            raise PromptCommandError(f"Active TenantConfig has invalid {label}", 1)
        execution = action["execution"]
        connection = connections.get(str(execution.get("connection_id")))
        if connection is None:
            raise PromptCommandError(
                f"Active TenantConfig {label} references an unavailable integration connection",
                1,
            )
        action_id = action.get("action_id")
        request_mapping = execution.get("request_mapping")
        if not isinstance(action_id, str) or not isinstance(request_mapping, str):
            raise PromptCommandError(f"Active TenantConfig has invalid {label}", 1)
        preset = next(
            (
                name
                for name, (inputs, mapping) in _POST_CALL_PRESETS.items()
                if action.get("type", "http.post_json") == "http.post_json"
                and action.get("inputs", {}) == inputs
                and request_mapping == mapping
                and action.get("semantic_key") == f"post_call.{action_id}"
                and action.get("semantic_version") == 1
                and execution.get("timeout_seconds") == 10
                and all(
                    execution.get(key) == value
                    for key, value in _POST_CALL_EXECUTION.items()
                )
            ),
            None,
        )
        if preset is not None:
            authored.append(
                {"id": action_id, "connection": connection, "preset": preset}
            )
            continue
        rendered: dict[str, Any] = {
            "id": action_id,
            "type": action.get("type", "http.post_json"),
            "connection": connection,
            "request_mapping": request_mapping,
            "timeout_seconds": execution.get("timeout_seconds", 10),
        }
        if action.get("inputs"):
            rendered["inputs"] = action["inputs"]
        authored.append(rendered)
    return canonical_config({**result, "post_call_actions": authored})


def serialize_tenant_yaml(config: Mapping[str, Any]) -> str:
    return yaml.safe_dump(
        canonical_config(config),
        allow_unicode=True,
        default_flow_style=False,
        indent=2,
        sort_keys=False,
    )


def semantic_diff(old: object, new: object, path: str = "") -> list[ConfigDiff]:
    if isinstance(old, dict) and isinstance(new, dict):
        keys = list(old) + [key for key in new if key not in old]
        differences: list[ConfigDiff] = []
        for key in keys:
            child = f"{path}.{key}".strip(".")
            if key not in old:
                differences.append(ConfigDiff(child, _MISSING, new[key]))
            elif key not in new:
                differences.append(ConfigDiff(child, old[key], _MISSING))
            else:
                differences.extend(semantic_diff(old[key], new[key], child))
        return differences
    if old != new:
        return [ConfigDiff(path or "<root>", old, new)]
    return []


class _Missing:
    pass


_MISSING = _Missing()


def _read(path: Path, *, required: bool) -> dict[str, Any] | None:
    try:
        return parse_tenant_yaml(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if not required:
            return None
        raise PromptCommandError(
            f"missing canonical TenantConfig file: {path}", 2
        ) from None
    except (OSError, UnicodeDecodeError) as error:
        raise PromptCommandError(
            f"cannot read canonical TenantConfig file {path}: {error}", 2
        ) from error


def _config_response_error(response: Response[Any]) -> None:
    if response.status_code == 412:
        raise PromptCommandError("remote config draft changed; run plan and retry")
    if response.status_code == 409:
        raise PromptCommandError("remote config state changed; run plan and retry")
    _response_error(response)


def _state(client: AuthenticatedClient, tenant_id: UUID) -> ConfigState:
    revisions_response = list_config_revisions_admin_v1_tenants_tenant_id_config_revisions_get.sync_detailed(
        tenant_id, client=client
    )
    _config_response_error(revisions_response)
    if not isinstance(revisions_response.parsed, list) or not all(
        isinstance(item, ConfigRevisionResponse) for item in revisions_response.parsed
    ):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    active_response = (
        get_active_config_admin_v1_tenants_tenant_id_config_active_get.sync_detailed(
            tenant_id, client=client
        )
    )
    if active_response.status_code == 404:
        active = None
    else:
        _config_response_error(active_response)
        if not isinstance(active_response.parsed, ActiveTenantConfig):
            raise PromptCommandError(
                "unexpected client failure: invalid Backend response", 1
            )
        active = active_response.parsed
    draft = max(
        (
            item
            for item in revisions_response.parsed
            if item.status is ConfigRevisionStatus.DRAFT
        ),
        key=lambda item: item.revision_number,
        default=None,
    )
    return ConfigState(list(revisions_response.parsed), active, draft)


def _validate(
    client: AuthenticatedClient,
    tenant_id: UUID,
    config: Mapping[str, Any],
    schema_version: int,
    *,
    local: bool,
) -> dict[str, Any] | None:
    runtime_config = compile_authoring_config(client, tenant_id, config)
    response = (
        validate_config_admin_v1_tenants_tenant_id_config_validate_post.sync_detailed(
            tenant_id,
            client=client,
            body=ValidateConfigRequest(
                config=ValidateConfigRequestConfig.from_dict(runtime_config),
                schema_version=schema_version,
            ),
        )
    )
    _config_response_error(response)
    if not isinstance(response.parsed, ValidateConfigResponse):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    if not response.parsed.valid:
        if not local:
            return None
        issues = response.parsed.errors
        lines = ["Invalid TenantConfig"]
        if not isinstance(issues, Unset):
            for issue in issues:
                lines.extend(("", f"{issue.path}:", f"  {issue.message}"))
        raise PromptCommandError("\n".join(lines), 2)
    normalized = response.parsed.normalized_config
    if not isinstance(normalized, ValidateConfigResponseNormalizedConfigType0):
        raise PromptCommandError(
            "unexpected client failure: missing normalized config", 1
        )
    return canonical_config(normalized.to_dict())


def _schema_version(config: Mapping[str, Any], context: str) -> int:
    version = config.get("schema_version")
    if type(version) is not int or version != CURRENT_SCHEMA_VERSION:
        raise PromptCommandError(
            f"{context} uses TenantConfig schema version {version!r}; explicit migration "
            f"to writable schema {CURRENT_SCHEMA_VERSION} is required",
            2,
        )
    return version


def _active_config(state: ConfigState) -> dict[str, Any]:
    if state.active is None:
        raise PromptCommandError("tenant has no active TenantConfig")
    config = state.active.config.to_dict()
    _schema_version(config, "Active TenantConfig")
    return canonical_config(config)


def _comparison_config(
    client: AuthenticatedClient, tenant_id: UUID, state: ConfigState
) -> dict[str, Any] | None:
    if state.draft is not None:
        raw = state.draft.config.to_dict()
        _schema_version(raw, "Remote draft")
        return _validate(
            client,
            tenant_id,
            raw,
            state.draft.schema_version,
            local=False,
        ) or canonical_config(raw)
    if state.active is not None:
        return _active_config(state)
    return None


def _show(slug: str, state: ConfigState) -> None:
    print(f"Tenant Config: {slug}\n")
    if state.active is None:
        print("Active revision: none")
    else:
        config = state.active.config.to_dict()
        print(f"Active revision: {state.active.revision_number}")
        print(f"Schema version: {config.get('schema_version', 'unknown')}")
    if state.draft is None:
        print("Draft revision: none")
    else:
        print(f"Draft revision: {state.draft.revision_number}")
        print(f"Draft schema: {state.draft.schema_version}")
        print(f"Draft version: {state.draft.version}")


def _revisions(state: ConfigState) -> None:
    if not state.revisions:
        print("No revisions.")
        return
    print("REVISION\tSCHEMA\tSTATUS\tCREATED/PUBLISHED")
    for revision in state.revisions:
        timestamp = revision.published_at or revision.created_at
        print(
            f"{revision.revision_number}\t{revision.schema_version}\t"
            f"{revision.status.value}\t{timestamp.isoformat()}"
        )


def _write(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
    except OSError as error:
        raise PromptCommandError(
            f"cannot write canonical TenantConfig file {path}: {error}", 2
        ) from error


def _pull(
    client: AuthenticatedClient,
    tenant_id: UUID,
    path: Path,
    state: ConfigState,
    *,
    force: bool,
) -> None:
    remote = authoring_config(client, tenant_id, _active_config(state))
    if path.exists() and not force:
        local = _read(path, required=True)
        assert local is not None
        if canonical_config(local) == remote:
            print(f"Already current: {path}")
            return
        raise PromptCommandError(
            "Local tenant.yaml differs from remote active configuration. Use --force to overwrite it.",
            2,
        )
    content = serialize_tenant_yaml(remote)
    _write(path, content)
    assert state.active is not None
    print(
        f"Wrote active revision {state.active.revision_number} "
        f"(schema {CURRENT_SCHEMA_VERSION}) to {path}"
    )


def _format_value(value: object) -> str:
    if value is _MISSING:
        return "<missing>"
    return json.dumps(value, ensure_ascii=False, default=str)


def _print_plan(
    slug: str,
    path: Path,
    state: ConfigState,
    local: dict[str, Any] | None,
    remote: dict[str, Any] | None,
) -> None:
    status = plan_status(local, remote, state)
    print(f"Tenant Config: {slug}\n\nStatus: {status}\n")
    print(f"Local:\n  {path}")
    if local is not None:
        print(f"  schema: {CURRENT_SCHEMA_VERSION}")
    print("\nRemote:")
    print(
        "  active revision: "
        + (str(state.active.revision_number) if state.active else "none")
    )
    print(
        "  draft revision: "
        + (str(state.draft.revision_number) if state.draft else "none")
    )
    if state.draft is not None:
        print(f"  draft version: {state.draft.version}")
        print(f"  schema: {state.draft.schema_version}")
    elif state.active is not None:
        print(
            f"  schema: {_schema_version(state.active.config.to_dict(), 'Active TenantConfig')}"
        )
    if local is not None and remote is not None and local != remote:
        changes = semantic_diff(remote, local)
        print("\nChanges:")
        for change in changes[:MAX_DIFFS]:
            print(f"  {change.path}")
            print(f"    {_format_value(change.old)} -> {_format_value(change.new)}")
        if len(changes) > MAX_DIFFS:
            print(f"  ... {len(changes) - MAX_DIFFS} more changes")
    print("\nPlan:")
    if local is None:
        print("  no mutation; create tenant.yaml or run pull")
    elif status == "unchanged":
        print("  no changes")
    elif state.draft is not None:
        print(f"  update existing draft revision {state.draft.revision_number}")
        print("  validate draft")
        print("  no publication")
    else:
        print("  create draft revision")
        print("  validate draft")
        print("  no publication")


def plan_status(
    local: dict[str, Any] | None,
    remote: dict[str, Any] | None,
    state: ConfigState,
) -> str:
    if local is None:
        return "missing-local"
    if remote is None:
        return "local-only"
    if local == remote:
        return "unchanged"
    return "draft-conflict" if state.draft is not None else "modified"


def _plan(
    client: AuthenticatedClient,
    tenant: TenantResponse,
    path: Path,
) -> None:
    raw = _read(path, required=False)
    local = (
        _validate(client, tenant.id, raw, CURRENT_SCHEMA_VERSION, local=True)
        if raw is not None
        else None
    )
    state = _state(client, tenant.id)
    remote = _comparison_config(client, tenant.id, state)
    _print_plan(tenant.slug, path, state, local, remote)


def _expect_revision(response: Response[Any]) -> ConfigRevisionResponse:
    _config_response_error(response)
    if not isinstance(response.parsed, ConfigRevisionResponse):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def _validate_saved_draft(
    client: AuthenticatedClient, tenant_id: UUID, revision_id: UUID
) -> None:
    response = validate_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_validate_post.sync_detailed(
        tenant_id, revision_id, client=client
    )
    _config_response_error(response)
    if not isinstance(response.parsed, ValidateDraftResponse):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    if not response.parsed.valid:
        raise PromptCommandError("Backend rejected the saved TenantConfig draft")


def _push(
    client: AuthenticatedClient,
    tenant: TenantResponse,
    path: Path,
) -> None:
    raw = _read(path, required=True)
    assert raw is not None
    local = _validate(client, tenant.id, raw, CURRENT_SCHEMA_VERSION, local=True)
    assert local is not None
    state = _state(client, tenant.id)
    remote = _comparison_config(client, tenant.id, state)
    if local == remote:
        target = state.draft or state.active
        assert target is not None
        print(f"No changes; revision {target.revision_number} is current.")
        return
    if state.draft is None:
        response = create_config_draft_admin_v1_tenants_tenant_id_config_drafts_post.sync_detailed(
            tenant.id,
            client=client,
            body=CreateDraftRequest(
                config=CreateDraftRequestConfigType0.from_dict(local),
                schema_version=CURRENT_SCHEMA_VERSION,
            ),
        )
    else:
        response = update_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_patch.sync_detailed(
            tenant.id,
            state.draft.id,
            client=client,
            body=UpdateDraftRequest(
                config=UpdateDraftRequestConfigType0.from_dict(local),
                schema_version=CURRENT_SCHEMA_VERSION,
            ),
            if_match=f'"{state.draft.version}"',
        )
    revision = _expect_revision(response)
    _validate_saved_draft(client, tenant.id, revision.id)
    print(f"Draft revision {revision.revision_number}, version {revision.version}")


def _publish(
    client: AuthenticatedClient, tenant: TenantResponse, state: ConfigState
) -> None:
    if state.draft is None:
        raise PromptCommandError(
            f"Tenant Config '{tenant.slug}' has no draft to publish"
        )
    response = publish_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_publish_post.sync_detailed(
        tenant.id, state.draft.id, client=client
    )
    revision = _expect_revision(response)
    print(
        f"Published Tenant Config for '{tenant.slug}' revision {revision.revision_number}."
    )
    print(
        "New calls will use this config revision. Existing calls remain pinned to their previous config revision."
    )


def run_tenant_config(
    settings: Settings,
    action: str,
    slug: str,
    *,
    force: bool = False,
) -> None:
    path = tenant_config_path(settings.state_dir, slug)
    with _client(settings) as client:
        tenant = _tenant(client, slug)
        if action == "show":
            _show(slug, _state(client, tenant.id))
        elif action == "revisions":
            _revisions(_state(client, tenant.id))
        elif action == "pull":
            _pull(client, tenant.id, path, _state(client, tenant.id), force=force)
        elif action == "plan":
            _plan(client, tenant, path)
        elif action == "push":
            _push(client, tenant, path)
        elif action == "publish":
            _publish(client, tenant, _state(client, tenant.id))
        else:
            raise PromptCommandError(f"unsupported TenantConfig action: {action}", 2)
