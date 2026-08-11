from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from admin_client.generated.models.active_tenant_config import ActiveTenantConfig
from admin_client.generated.models.config_revision_response import (
    ConfigRevisionResponse,
)
from admin_client.generated.models.integration_connection_response import (
    IntegrationConnectionResponse,
)
from admin_client.generated.models.tenant_response import TenantResponse
from admin_client.generated.models.tenant_status import TenantStatus
from admin_client.generated.models.validate_config_response import (
    ValidateConfigResponse,
)
from admin_client.generated.models.validate_draft_response import ValidateDraftResponse
from admin_client.generated.types import Response
from contracts import TenantConfigV3
from control_plane.commands import prompts, tenant_configs
from control_plane.settings import Settings

NOW = datetime(2026, 8, 10, tzinfo=UTC)
TENANT_ID = UUID("00000000-0000-0000-0000-000000000010")
SLUG = "penzion-grand"
CONFIG: dict[str, Any] = {
    "schema_version": 3,
    "business": {"name": "Penzión Grand", "type": "hotel"},
    "contact": {
        "address": None,
        "phones": ["+421900000000"],
        "emails": ["info@example.com"],
        "website": None,
    },
    "localization": {
        "default_locale": "sk-SK",
        "timezone": "Europe/Bratislava",
    },
    "agent": {
        "display_name": "Amélia",
        "greeting": "Dobrý deň",
        "profile": "hotel_assistant",
    },
    "conversation": {"scope": "property_only"},
    "capabilities": {},
}


def settings(path: Path) -> Settings:
    return Settings("https://backend.example", "secret", path)


def tenant() -> TenantResponse:
    return TenantResponse(
        active_config_revision_id=None,
        active_prompt_set_revision_id=None,
        business_type="hotel",
        created_at=NOW,
        display_name="Penzión Grand",
        id=TENANT_ID,
        slug=SLUG,
        status=TenantStatus.ACTIVE,
        updated_at=NOW,
    )


def revision(
    number: int,
    status: str,
    config: dict[str, Any] | None = None,
    *,
    schema_version: int = 3,
    version: int = 1,
) -> ConfigRevisionResponse:
    return ConfigRevisionResponse.from_dict(
        {
            "comment": None,
            "config": config or CONFIG,
            "created_at": NOW.isoformat(),
            "created_by": None,
            "id": str(UUID(int=number)),
            "published_at": NOW.isoformat() if status == "published" else None,
            "revision_number": number,
            "schema_version": schema_version,
            "status": status,
            "tenant_id": str(TENANT_ID),
            "version": version,
        }
    )


def active(number: int = 1, config: dict[str, Any] | None = None) -> ActiveTenantConfig:
    return ActiveTenantConfig.from_dict(
        {
            "config": config or CONFIG,
            "published_at": NOW.isoformat(),
            "revision_id": str(UUID(int=number)),
            "revision_number": number,
            "tenant_id": str(TENANT_ID),
        }
    )


def response(
    parsed: object,
    status: HTTPStatus = HTTPStatus.OK,
    content: bytes = b"",
) -> Response[object]:
    return Response(
        status_code=status,
        content=content,
        headers=httpx.Headers(),
        parsed=parsed,
    )


def integration_connection(
    *,
    key: str = "recording_webhook",
    connection_id: int = 99,
    provider: str = "managed_webhook",
    status: str = "active",
) -> IntegrationConnectionResponse:
    return IntegrationConnectionResponse.from_dict(
        {
            "created_at": NOW.isoformat(),
            "credential_ref": "managed-webhook-recording",
            "id": f"00000000-0000-0000-0000-{connection_id:012d}",
            "key": key,
            "provider": provider,
            "status": status,
            "tenant_id": str(TENANT_ID),
            "updated_at": NOW.isoformat(),
        }
    )


def authoring_post_call_config() -> dict[str, Any]:
    return {
        **CONFIG,
        "post_call_actions": [
            {
                "id": "send_recording",
                "type": "http.post_json",
                "connection": "recording_webhook",
                "inputs": {
                    "recording": {
                        "artifact": "call_recording",
                        "representation": "base64_text",
                    }
                },
                "request_mapping": '{"recording": inputs.recording.body}',
                "timeout_seconds": 10,
            }
        ],
    }


def preset_post_call_config() -> dict[str, Any]:
    return {
        **CONFIG,
        "post_call_actions": [
            {
                "id": "send_transcript",
                "connection": "transcript_webhook",
                "preset": "transcript.raw_json",
            },
            {
                "id": "send_recording",
                "connection": "recording_webhook",
                "preset": "recording.base64",
            },
        ],
    }


def mock_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tenant_configs.list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
        "sync_detailed",
        lambda tenant_id, *, client: response([integration_connection()]),
    )


def mock_preset_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tenant_configs.list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
        "sync_detailed",
        lambda tenant_id, *, client: response(
            [
                integration_connection(key="transcript_webhook", connection_id=98),
                integration_connection(),
            ]
        ),
    )


def mock_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        prompts.get_tenant_by_slug_admin_v1_tenants_by_slug_slug_get,
        "sync_detailed",
        lambda slug, *, client: response(tenant()),
    )


def mock_state(
    monkeypatch: pytest.MonkeyPatch,
    revisions: list[ConfigRevisionResponse],
    active_config: ActiveTenantConfig | None,
) -> None:
    mock_tenant(monkeypatch)
    monkeypatch.setattr(
        tenant_configs.list_config_revisions_admin_v1_tenants_tenant_id_config_revisions_get,
        "sync_detailed",
        lambda tenant_id, *, client: response(revisions),
    )
    monkeypatch.setattr(
        tenant_configs.get_active_config_admin_v1_tenants_tenant_id_config_active_get,
        "sync_detailed",
        lambda tenant_id, *, client: (
            response(active_config)
            if active_config is not None
            else response(None, HTTPStatus.NOT_FOUND)
        ),
    )


def mock_validation(
    monkeypatch: pytest.MonkeyPatch,
    normalized: dict[str, Any] | None = None,
) -> list[object]:
    calls: list[object] = []

    def validate(tenant_id: UUID, *, client: object, body: object) -> Response[object]:
        calls.append(body)
        return response(
            ValidateConfigResponse.from_dict(
                {
                    "valid": True,
                    "errors": [],
                    "normalized_config": normalized or CONFIG,
                }
            )
        )

    monkeypatch.setattr(
        tenant_configs.validate_config_admin_v1_tenants_tenant_id_config_validate_post,
        "sync_detailed",
        validate,
    )
    return calls


def write_yaml(path: Path, config: dict[str, Any] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        tenant_configs.serialize_tenant_yaml(config or CONFIG), encoding="utf-8"
    )


def test_yaml_parser_is_safe_single_mapping_current_schema() -> None:
    assert (
        tenant_configs.parse_tenant_yaml(tenant_configs.serialize_tenant_yaml(CONFIG))
        == CONFIG
    )
    for document, message in (
        ("schema_version: [", "invalid TenantConfig YAML"),
        ("- schema_version: 3\n", "root must be a mapping"),
        ("schema_version: 3\n---\nschema_version: 3\n", "exactly one document"),
        (
            "!!python/object/apply:os.system ['echo unsafe']",
            "invalid TenantConfig YAML",
        ),
        ("schema_version: 2\n", "not writable"),
        ("schema_version: 3\ncreated: 2026-08-10\n", "JSON-compatible"),
    ):
        with pytest.raises(tenant_configs.PromptCommandError, match=message):
            tenant_configs.parse_tenant_yaml(document)


def test_serialization_is_deterministic_unicode_and_metadata_free() -> None:
    config = {**CONFIG, "capabilities": {"z": False, "a": True}}
    first = tenant_configs.serialize_tenant_yaml(config)
    second = tenant_configs.serialize_tenant_yaml(config)
    assert first == second
    assert first.endswith("\n") and not first.endswith("\n\n")
    assert "Penzión Grand" in first
    assert first.index("  a: true") < first.index("  z: false")
    for field in ("revision_id", "revision_number", "version", "published_at"):
        assert not any(line.startswith(f"{field}:") for line in first.splitlines())


def test_post_call_authoring_actions_compile_and_render_without_runtime_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_connections(monkeypatch)
    authored = authoring_post_call_config()

    compiled = tenant_configs.compile_authoring_config(
        object(),
        TENANT_ID,
        authored,  # type: ignore[arg-type]
    )

    action = compiled["post_call_actions"][0]
    assert action == {
        "action_id": "send_recording",
        "type": "http.post_json",
        "inputs": authored["post_call_actions"][0]["inputs"],
        "semantic_key": "post_call.send_recording",
        "semantic_version": 1,
        "execution": {
            "plan_type": "managed_webhook.post_json.v1",
            "connection_id": "00000000-0000-0000-0000-000000000099",
            "mapping_language": "jsonata",
            "mapping_contract_version": 1,
            "mapping_engine": "jsonata-python",
            "mapping_engine_version": "0.7.0",
            "request_mapping": '{"recording": inputs.recording.body}',
            "timeout_seconds": 10,
        },
    }
    assert (
        tenant_configs.authoring_config(
            object(),
            TENANT_ID,
            compiled,  # type: ignore[arg-type]
        )
        == authored
    )


def test_post_call_presets_compile_to_strict_runtime_and_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_preset_connections(monkeypatch)
    authored = preset_post_call_config()

    compiled = tenant_configs.compile_authoring_config(
        object(),
        TENANT_ID,
        authored,  # type: ignore[arg-type]
    )

    transcript, recording = compiled["post_call_actions"]
    assert transcript["inputs"] == {
        "transcript": {"artifact": "transcript", "representation": "raw_json"}
    }
    assert transcript["execution"]["request_mapping"] == (
        '{"call_id": call_id, "messages": inputs.transcript.value}'
    )
    assert recording["inputs"] == {
        "recording": {
            "artifact": "call_recording",
            "representation": "base64_text",
        }
    }
    assert recording["execution"]["request_mapping"] == (
        '{"call_id": call_id, "recording": inputs.recording.body}'
    )
    TenantConfigV3.model_validate(compiled)
    pulled = tenant_configs.authoring_config(
        object(),
        TENANT_ID,
        compiled,  # type: ignore[arg-type]
    )
    assert pulled == authored
    assert "execution" not in pulled["post_call_actions"][0]
    assert "credential_ref" not in str(pulled)


def test_post_call_preset_validation_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_connections(monkeypatch)
    unknown = {
        **CONFIG,
        "post_call_actions": [
            {
                "id": "send_recording",
                "connection": "recording_webhook",
                "preset": "recording.unknown",
            }
        ],
    }
    with pytest.raises(tenant_configs.PromptCommandError, match="preset is unknown"):
        tenant_configs.compile_authoring_config(
            object(),
            TENANT_ID,
            unknown,  # type: ignore[arg-type]
        )

    mixed = {
        **unknown,
        "post_call_actions": [
            {
                **unknown["post_call_actions"][0],
                "preset": "recording.base64",
                "request_mapping": "{}",
            }
        ],
    }
    with pytest.raises(tenant_configs.PromptCommandError, match="unknown fields"):
        tenant_configs.compile_authoring_config(
            object(),
            TENANT_ID,
            mixed,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("provider", "status"),
    [("google_sheets", "active"), ("managed_webhook", "disabled")],
)
def test_post_call_actions_reject_incompatible_connections(
    monkeypatch: pytest.MonkeyPatch, provider: str, status: str
) -> None:
    monkeypatch.setattr(
        tenant_configs.list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
        "sync_detailed",
        lambda tenant_id, *, client: response(
            [integration_connection(provider=provider, status=status)]
        ),
    )
    with pytest.raises(
        tenant_configs.PromptCommandError, match="active managed_webhook"
    ):
        tenant_configs.compile_authoring_config(
            object(),
            TENANT_ID,
            {
                **CONFIG,
                "post_call_actions": [
                    {
                        "id": "send_recording",
                        "connection": "recording_webhook",
                        "preset": "recording.base64",
                    }
                ],
            },  # type: ignore[arg-type]
        )


def test_post_call_actions_reject_ambiguous_connection_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tenant_configs.list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
        "sync_detailed",
        lambda tenant_id, *, client: response(
            [integration_connection(), integration_connection(connection_id=100)]
        ),
    )
    with pytest.raises(
        tenant_configs.PromptCommandError, match="ambiguous integration"
    ):
        tenant_configs.compile_authoring_config(
            object(),
            TENANT_ID,
            authoring_post_call_config(),  # type: ignore[arg-type]
        )


def test_post_call_authoring_action_requires_a_known_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tenant_configs.list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
        "sync_detailed",
        lambda tenant_id, *, client: response([]),
    )

    with pytest.raises(tenant_configs.PromptCommandError, match="unknown integration"):
        tenant_configs.compile_authoring_config(
            object(),
            TENANT_ID,
            authoring_post_call_config(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("action", ["plan", "push"])
def test_plan_and_push_reject_missing_post_call_connection_before_backend_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, action: str
) -> None:
    write_yaml(
        tenant_configs.tenant_config_path(tmp_path, SLUG), preset_post_call_config()
    )
    mock_tenant(monkeypatch)
    monkeypatch.setattr(
        tenant_configs.list_connections_admin_v1_tenants_tenant_id_integration_connections_get,
        "sync_detailed",
        lambda tenant_id, *, client: response([]),
    )
    monkeypatch.setattr(
        tenant_configs.validate_config_admin_v1_tenants_tenant_id_config_validate_post,
        "sync_detailed",
        lambda *args, **kwargs: pytest.fail("invalid authoring must not reach Backend"),
    )

    with pytest.raises(tenant_configs.PromptCommandError, match="unknown integration"):
        tenant_configs.run_tenant_config(settings(tmp_path), action, SLUG)


def test_semantic_comparison_ignores_mapping_order_but_not_list_order() -> None:
    reordered = dict(reversed(list(CONFIG.items())))
    assert not tenant_configs.semantic_diff(CONFIG, reordered)
    changed = {**CONFIG, "contact": {**CONFIG["contact"], "phones": ["b", "a"]}}
    reverse = {**changed, "contact": {**changed["contact"], "phones": ["a", "b"]}}
    assert tenant_configs.semantic_diff(changed, reverse)[0].path == "contact.phones"


def test_path_reuses_state_root_and_slug_safety(tmp_path: Path) -> None:
    assert tenant_configs.tenant_config_path(tmp_path, SLUG) == (
        tmp_path / "tenants" / SLUG / "tenant.yaml"
    )
    for slug in ("../escape", "/absolute", "tenant/name", "UPPER", "a--b"):
        with pytest.raises(tenant_configs.PromptCommandError, match="tenant slug"):
            tenant_configs.tenant_config_path(tmp_path, slug)


def test_unknown_tenant_is_clear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        prompts.get_tenant_by_slug_admin_v1_tenants_by_slug_slug_get,
        "sync_detailed",
        lambda slug, *, client: response(
            None, HTTPStatus.NOT_FOUND, b'{"detail":"tenant not found"}'
        ),
    )
    with pytest.raises(
        tenant_configs.PromptCommandError, match=f"unknown tenant: {SLUG}"
    ):
        tenant_configs.run_tenant_config(settings(tmp_path), "show", SLUG)


def test_show_and_revisions_read_backend_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tenant_configs.tenant_config_path(tmp_path, SLUG)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff")
    mock_state(
        monkeypatch,
        [revision(1, "archived", schema_version=1), revision(2, "draft", version=4)],
        active(1, {**CONFIG, "schema_version": 3}),
    )

    tenant_configs.run_tenant_config(settings(tmp_path), "show", SLUG)
    output = capsys.readouterr().out
    assert "Active revision: 1" in output
    assert "Draft version: 4" in output

    tenant_configs.run_tenant_config(settings(tmp_path), "revisions", SLUG)
    output = capsys.readouterr().out
    assert "1\t1\tarchived" in output
    assert "2\t3\tdraft" in output


def test_pull_creates_semantic_noop_refuses_and_force_overwrites(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_state(monkeypatch, [revision(4, "published")], active(4))
    path = tenant_configs.tenant_config_path(tmp_path, SLUG)

    tenant_configs.run_tenant_config(settings(tmp_path), "pull", SLUG)
    assert tenant_configs.parse_tenant_yaml(path.read_text()) == CONFIG
    assert "active revision 4" in capsys.readouterr().out

    path.write_text(
        "\n".join(
            tenant_configs.serialize_tenant_yaml(
                dict(reversed(list(CONFIG.items())))
            ).splitlines()
        )
        + "\n",
        encoding="utf-8",
    )
    tenant_configs.run_tenant_config(settings(tmp_path), "pull", SLUG)
    assert "Already current" in capsys.readouterr().out

    changed = {**CONFIG, "business": {"name": "Local", "type": "hotel"}}
    write_yaml(path, changed)
    with pytest.raises(tenant_configs.PromptCommandError, match="--force"):
        tenant_configs.run_tenant_config(settings(tmp_path), "pull", SLUG)
    assert tenant_configs.parse_tenant_yaml(path.read_text()) == changed

    path.write_bytes(b"\xff")
    tenant_configs.run_tenant_config(settings(tmp_path), "pull", SLUG, force=True)
    assert tenant_configs.parse_tenant_yaml(path.read_text()) == CONFIG


def test_pull_renders_post_call_actions_as_authoring_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_preset_connections(monkeypatch)
    authored = preset_post_call_config()
    runtime = tenant_configs.compile_authoring_config(
        object(),
        TENANT_ID,
        authored,  # type: ignore[arg-type]
    )
    mock_state(monkeypatch, [revision(4, "published", runtime)], active(4, runtime))

    path = tenant_configs.tenant_config_path(tmp_path, SLUG)
    tenant_configs.run_tenant_config(settings(tmp_path), "pull", SLUG)

    assert tenant_configs.parse_tenant_yaml(path.read_text()) == authored


def test_plan_validates_then_reads_remote_and_prints_path_diff_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tenant_configs.tenant_config_path(tmp_path, SLUG)
    local = {**CONFIG, "contact": {**CONFIG["contact"], "phones": ["+421911"]}}
    write_yaml(path, local)
    order: list[str] = []
    mock_tenant(monkeypatch)

    def validate_candidate(
        tenant_id: UUID, *, client: object, body: object
    ) -> Response[object]:
        order.append("validate")
        return response(
            ValidateConfigResponse.from_dict(
                {"valid": True, "errors": [], "normalized_config": local}
            )
        )

    def list_revisions(tenant_id: UUID, *, client: object) -> Response[object]:
        order.append("read")
        return response([revision(1, "published")])

    monkeypatch.setattr(
        tenant_configs.validate_config_admin_v1_tenants_tenant_id_config_validate_post,
        "sync_detailed",
        validate_candidate,
    )
    monkeypatch.setattr(
        tenant_configs.list_config_revisions_admin_v1_tenants_tenant_id_config_revisions_get,
        "sync_detailed",
        list_revisions,
    )
    monkeypatch.setattr(
        tenant_configs.get_active_config_admin_v1_tenants_tenant_id_config_active_get,
        "sync_detailed",
        lambda tenant_id, *, client: response(active()),
    )

    tenant_configs.run_tenant_config(settings(tmp_path), "plan", SLUG)
    output = capsys.readouterr().out
    assert order == ["validate", "read"]
    assert "Status: modified" in output
    assert "contact.phones" in output
    assert "create draft revision" in output


def test_plan_missing_local_and_existing_draft_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    draft_config = {**CONFIG, "business": {"name": "Draft", "type": "hotel"}}
    mock_state(
        monkeypatch,
        [revision(1, "published"), revision(2, "draft", draft_config, version=3)],
        active(),
    )
    validation_results = iter((draft_config, CONFIG, draft_config))
    monkeypatch.setattr(
        tenant_configs.validate_config_admin_v1_tenants_tenant_id_config_validate_post,
        "sync_detailed",
        lambda tenant_id, *, client, body: response(
            ValidateConfigResponse.from_dict(
                {
                    "valid": True,
                    "errors": [],
                    "normalized_config": next(validation_results),
                }
            )
        ),
    )
    tenant_configs.run_tenant_config(settings(tmp_path), "plan", SLUG)
    assert "Status: missing-local" in capsys.readouterr().out

    write_yaml(tenant_configs.tenant_config_path(tmp_path, SLUG), CONFIG)
    tenant_configs.run_tenant_config(settings(tmp_path), "plan", SLUG)
    output = capsys.readouterr().out
    assert "Status: draft-conflict" in output
    assert "update existing draft revision 2" in output


def test_backend_validation_paths_are_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tenant_configs.tenant_config_path(tmp_path, SLUG)
    write_yaml(path)
    mock_tenant(monkeypatch)
    monkeypatch.setattr(
        tenant_configs.validate_config_admin_v1_tenants_tenant_id_config_validate_post,
        "sync_detailed",
        lambda tenant_id, *, client, body: response(
            ValidateConfigResponse.from_dict(
                {
                    "valid": False,
                    "errors": [
                        {
                            "path": "localization.timezone",
                            "code": "invalid_timezone",
                            "message": "Unknown IANA timezone",
                        }
                    ],
                    "normalized_config": None,
                }
            )
        ),
    )
    with pytest.raises(
        tenant_configs.PromptCommandError,
        match=r"localization\.timezone:\n  Unknown IANA timezone",
    ):
        tenant_configs.run_tenant_config(settings(tmp_path), "plan", SLUG)


def test_push_creates_validated_draft_and_never_publishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tenant_configs.tenant_config_path(tmp_path, SLUG)
    write_yaml(path)
    mock_state(monkeypatch, [], None)
    mock_validation(monkeypatch)
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        tenant_configs.create_config_draft_admin_v1_tenants_tenant_id_config_drafts_post,
        "sync_detailed",
        lambda tenant_id, *, client, body: (
            seen.update(body=body) or response(revision(1, "draft"), HTTPStatus.CREATED)
        ),
    )
    monkeypatch.setattr(
        tenant_configs.validate_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_validate_post,
        "sync_detailed",
        lambda tenant_id, revision_id, *, client: response(
            ValidateDraftResponse.from_dict({"valid": True, "errors": []})
        ),
    )
    monkeypatch.setattr(
        tenant_configs.publish_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_publish_post,
        "sync_detailed",
        lambda *args, **kwargs: pytest.fail("push must not publish"),
    )

    tenant_configs.run_tenant_config(settings(tmp_path), "push", SLUG)
    assert isinstance(seen["body"], tenant_configs.CreateDraftRequest)
    assert seen["body"].to_dict()["config"] == CONFIG


def test_push_updates_with_etag_and_semantic_noop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tenant_configs.tenant_config_path(tmp_path, SLUG)
    changed = {**CONFIG, "business": {"name": "Changed", "type": "hotel"}}
    write_yaml(path, changed)
    draft = revision(2, "draft", CONFIG, version=7)
    mock_state(monkeypatch, [revision(1, "published"), draft], active())
    validation_results = iter((changed, CONFIG))

    def validate(tenant_id: UUID, *, client: object, body: object) -> Response[object]:
        return response(
            ValidateConfigResponse.from_dict(
                {
                    "valid": True,
                    "errors": [],
                    "normalized_config": next(validation_results),
                }
            )
        )

    monkeypatch.setattr(
        tenant_configs.validate_config_admin_v1_tenants_tenant_id_config_validate_post,
        "sync_detailed",
        validate,
    )
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        tenant_configs.update_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_patch,
        "sync_detailed",
        lambda tenant_id, revision_id, *, client, body, if_match: (
            seen.update(body=body, if_match=if_match)
            or response(revision(2, "draft", changed, version=8))
        ),
    )
    monkeypatch.setattr(
        tenant_configs.validate_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_validate_post,
        "sync_detailed",
        lambda tenant_id, revision_id, *, client: response(
            ValidateDraftResponse.from_dict({"valid": True, "errors": []})
        ),
    )
    tenant_configs.run_tenant_config(settings(tmp_path), "push", SLUG)
    assert seen["if_match"] == '"7"'
    assert isinstance(seen["body"], tenant_configs.UpdateDraftRequest)
    assert seen["body"].to_dict()["config"] == changed

    mock_state(monkeypatch, [revision(2, "draft", changed)], active())
    mock_validation(monkeypatch, changed)
    monkeypatch.setattr(
        tenant_configs.update_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_patch,
        "sync_detailed",
        lambda *args, **kwargs: pytest.fail("semantic no-op must not update"),
    )
    tenant_configs.run_tenant_config(settings(tmp_path), "push", SLUG)
    assert "No changes" in capsys.readouterr().out


@pytest.mark.parametrize(
    "status", [HTTPStatus.PRECONDITION_FAILED, HTTPStatus.CONFLICT]
)
def test_push_concurrency_conflicts_are_safe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: HTTPStatus
) -> None:
    changed = {**CONFIG, "business": {"name": "Changed", "type": "hotel"}}
    write_yaml(tenant_configs.tenant_config_path(tmp_path, SLUG), changed)
    mock_state(monkeypatch, [revision(2, "draft", CONFIG, version=7)], active())
    validation_results = iter((changed, CONFIG))
    monkeypatch.setattr(
        tenant_configs.validate_config_admin_v1_tenants_tenant_id_config_validate_post,
        "sync_detailed",
        lambda tenant_id, *, client, body: response(
            ValidateConfigResponse.from_dict(
                {
                    "valid": True,
                    "errors": [],
                    "normalized_config": next(validation_results),
                }
            )
        ),
    )
    monkeypatch.setattr(
        tenant_configs.update_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_patch,
        "sync_detailed",
        lambda *args, **kwargs: response(None, status),
    )
    with pytest.raises(tenant_configs.PromptCommandError, match="plan and retry"):
        tenant_configs.run_tenant_config(settings(tmp_path), "push", SLUG)


def test_publish_uses_remote_draft_without_reading_file_or_prompt_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tenant_configs.tenant_config_path(tmp_path, SLUG)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff")
    mock_state(monkeypatch, [revision(3, "draft")], active(2))
    seen: dict[str, UUID] = {}
    monkeypatch.setattr(
        tenant_configs.publish_config_draft_admin_v1_tenants_tenant_id_config_drafts_revision_id_publish_post,
        "sync_detailed",
        lambda tenant_id, revision_id, *, client: (
            seen.update(tenant_id=tenant_id, revision_id=revision_id)
            or response(revision(3, "published"))
        ),
    )

    tenant_configs.run_tenant_config(settings(tmp_path), "publish", SLUG)
    output = capsys.readouterr().out
    assert seen["revision_id"] == UUID(int=3)
    assert "New calls will use this config revision" in output
    assert "PromptSet" not in output


def test_old_active_schema_requires_explicit_migration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old = {
        "schema_version": 1,
        "localization": {"default_locale": "sk-SK", "timezone": "Europe/Bratislava"},
        "agent": {"display_name": "Amélia", "greeting": "Dobrý deň"},
        "conversation": {"scope": "property_only"},
        "capabilities": {},
    }
    mock_state(
        monkeypatch, [revision(1, "published", old, schema_version=1)], active(1, old)
    )
    with pytest.raises(tenant_configs.PromptCommandError, match="explicit migration"):
        tenant_configs.run_tenant_config(settings(tmp_path), "pull", SLUG)
