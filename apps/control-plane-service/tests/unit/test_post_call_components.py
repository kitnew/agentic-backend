from uuid import uuid4

import pytest
from control_plane.domain.capabilities import IntegrationConnectionRef
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentRegistry,
    PlatformScope,
    TenantScope,
)
from control_plane.domain.components.errors import (
    InvalidComponentValue,
    ScopeNotAllowed,
)
from control_plane.domain.post_call import (
    TenantPostCallConfig,
    register_post_call_components,
)
from pydantic import ValidationError


def action(action_id: str = "send_summary", **changes: object) -> dict[str, object]:
    return {
        "action_id": action_id,
        "inputs": {
            "summary": {"artifact": "call_summary", "representation": "plain_text"},
            "transcript": {"artifact": "transcript", "representation": "raw_json"},
        },
        "execution": {
            "integration_connection_ref": str(uuid4()),
            "method": "POST",
            "path": {"$expr": "'/calls/' & call.id"},
            "query": {"source": {"$expr": "agent.name"}},
            "headers": {"X-Trace": "trace"},
            "request": {
                "codec": "json",
                "mapping": {
                    "summary": {"$expr": "inputs.summary.value"},
                    "transcript": {"$expr": "inputs.transcript.value"},
                },
            },
            "response": {"codec": "json", "mapping": {"id": {"$expr": "response.id"}}},
            "timeout_seconds": 10,
            "result_schema": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
            },
        },
    } | changes


def test_post_call_round_trips_multiple_http_actions_and_mappings() -> None:
    value = TenantPostCallConfig.model_validate(
        {
            "actions": [
                action(),
                action(
                    "send_recording",
                    inputs={
                        "recording": {
                            "artifact": "call_recording",
                            "representation": "base64_text",
                        }
                    },
                ),
            ]
        }
    )
    assert isinstance(
        value.actions[0].execution.integration_connection_ref, IntegrationConnectionRef
    )
    assert value.model_dump(mode="json")["actions"][0]["execution"]["request"][
        "mapping"
    ]["transcript"] == {"$expr": "inputs.transcript.value"}
    assert (
        value.model_dump(mode="json")["actions"][0]["execution"]["plan_type"]
        == "http.request.v1"
    )


def test_post_call_rejects_unknown_fields_and_invalid_static_artifacts() -> None:
    with pytest.raises(ValidationError):
        TenantPostCallConfig.model_validate({"actions": [action(enabled=True)]})
    with pytest.raises(ValidationError, match="unsupported artifact representation"):
        TenantPostCallConfig.model_validate(
            {
                "actions": [
                    action(
                        inputs={
                            "recording": {
                                "artifact": "call_recording",
                                "representation": "plain_text",
                            }
                        }
                    )
                ]
            }
        )
    with pytest.raises(
        InvalidComponentValue, match="post-call action IDs must be unique"
    ):
        TenantPostCallConfig.model_validate({"actions": [action(), action()]})


def test_post_call_registry_is_tenant_only() -> None:
    registry = ComponentRegistry()
    register_post_call_components(registry)
    assert registry.resolve(
        ComponentAddress(ComponentKind("post_call.tenant"), TenantScope("t"))
    )
    with pytest.raises(ScopeNotAllowed):
        registry.resolve(
            ComponentAddress(ComponentKind("post_call.tenant"), PlatformScope())
        )
