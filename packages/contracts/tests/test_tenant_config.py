import json
from collections.abc import Callable
from pathlib import Path

import pytest
from contracts import (
    TENANT_CONFIG_SCHEMAS,
    ActiveTenantConfig,
    ConversationScope,
    ManagedWebhookExecution,
    ManagedWebhookResponseConfig,
    TenantCapabilityProfile,
    TenantConfigV1,
    TenantConfigV2,
    TenantConfigV3,
    TenantConfigV4,
    TenantConfigV5,
)
from pydantic import ValidationError

FIXTURE = Path(__file__).parent / "fixtures" / "tenant_config_v1.json"
V2_FIXTURE = Path(__file__).parent / "fixtures" / "tenant_config_v2.json"
WEBHOOK_PROFILE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "reservation_submit_webhook_profile.json"
)


def fixture_json() -> str:
    return FIXTURE.read_text()


def config_v3() -> dict[str, object]:
    return {
        "schema_version": 3,
        "business": {"name": "Fixture Hotel", "type": "hotel"},
        "contact": {"phones": ["+421900000000"]},
        "localization": {"default_locale": "sk-SK", "timezone": "Europe/Bratislava"},
        "agent": {
            "display_name": "Amelia",
            "greeting": "Dobry den",
            "profile": "hotel_assistant",
        },
        "conversation": {"scope": "property_only"},
        "capabilities": {},
    }


def config_v4() -> dict[str, object]:
    return {
        **config_v3(),
        "schema_version": 4,
        "handoff": {
            "destinations": {
                "reception": {
                    "description": "Reservations and general reception requests",
                    "phone_number": "+421900000001",
                }
            }
        },
    }


def config_v5() -> dict[str, object]:
    legacy = config_v4()
    handoff = legacy.pop("handoff")
    return {
        **legacy,
        "schema_version": 5,
        "telephony": {"phone_number": "+421551234567", "handoff": handoff},
    }


@pytest.mark.parametrize(
    ("version", "document"),
    [
        (1, lambda: json.loads(fixture_json())),
        (2, lambda: json.loads(V2_FIXTURE.read_text())),
        (3, config_v3),
        (4, config_v4),
        (5, config_v5),
    ],
)
def test_registered_schema_versions_parse_through_canonical_dispatch(
    version: int, document: Callable[[], dict[str, object]]
) -> None:
    assert sorted(TENANT_CONFIG_SCHEMAS) == [1, 2, 3, 4, 5]
    assert (
        TENANT_CONFIG_SCHEMAS[version].model_validate(document()).schema_version
        == version
    )


def test_canonical_schema_dispatch_rejects_unregistered_versions() -> None:
    assert TENANT_CONFIG_SCHEMAS.get(6) is None


def test_v5_telephony_requires_e164_for_number_and_destinations() -> None:
    parsed = TenantConfigV5.model_validate(config_v5())
    assert parsed.telephony.phone_number == "+421551234567"
    invalid = config_v5()
    invalid["telephony"] = {"phone_number": "0551234567"}
    with pytest.raises(ValidationError):
        TenantConfigV5.model_validate(invalid)


def test_v4_handoff_requires_semantic_keys_and_canonical_e164() -> None:
    parsed = TenantConfigV4.model_validate(config_v4())
    assert parsed.handoff.destinations["reception"].phone_number == "+421900000001"
    invalid = config_v4()
    invalid["handoff"] = {
        "destinations": {
            "reception": {"description": "Reception", "phone_number": "0900 1"}
        }
    }
    with pytest.raises(ValidationError):
        TenantConfigV4.model_validate(invalid)


def test_reservation_webhook_profile_fixture_has_bounded_semantic_response() -> None:
    profile = TenantCapabilityProfile.model_validate_json(
        WEBHOOK_PROFILE_FIXTURE.read_text()
    )

    assert isinstance(profile.execution, ManagedWebhookExecution)
    assert profile.execution.response is not None
    assert profile.execution.response.mode == "json"
    assert profile.execution.response.output_schema["additionalProperties"] is False


def test_webhook_response_mode_has_one_output_source() -> None:
    with pytest.raises(ValidationError, match="status_only requires only"):
        ManagedWebhookResponseConfig(
            mode="status_only",
            mapping='{"status": "wrong"}',
            success_output={"status": "submitted"},
            output_schema={"type": "object"},
        )


def test_v1_json_round_trip() -> None:
    config = TenantConfigV1.model_validate_json(fixture_json())

    assert json.loads(config.model_dump_json()) == json.loads(fixture_json())


def test_v1_fixture_remains_backward_compatible() -> None:
    config = TenantConfigV1.model_validate_json(fixture_json())

    assert config.schema_version == 1
    assert config.conversation.scope is ConversationScope.PROPERTY_ONLY


def test_v2_json_round_trip_and_requires_prompt_revision() -> None:
    config = TenantConfigV2.model_validate_json(V2_FIXTURE.read_text())

    assert json.loads(config.model_dump_json()) == json.loads(V2_FIXTURE.read_text())
    document = json.loads(V2_FIXTURE.read_text())
    document.pop("prompt_bundle_revision_id")
    with pytest.raises(ValidationError):
        TenantConfigV2.model_validate_json(json.dumps(document))


def test_v1_rejects_unknown_fields_and_schema_versions() -> None:
    document = json.loads(fixture_json())
    document["unknown"] = True
    with pytest.raises(ValidationError):
        TenantConfigV1.model_validate_json(json.dumps(document))
    document.pop("unknown")
    document["schema_version"] = 2
    with pytest.raises(ValidationError):
        TenantConfigV1.model_validate_json(json.dumps(document))


def test_v3_keeps_prompt_text_out_of_deterministic_configuration() -> None:
    config = config_v3()
    assert TenantConfigV3.model_validate(config).agent.profile == "hotel_assistant"
    with pytest.raises(ValidationError):
        TenantConfigV3.model_validate({**config, "knowledge_text": "Breakfast"})


def test_v3_validates_unique_declarative_post_call_actions() -> None:
    document = config_v3()
    action = {
        "action_id": "send_recording",
        "type": "http.post_json",
        "inputs": {
            "recording": {
                "artifact": "call_recording",
                "representation": "base64_text",
            }
        },
        "semantic_key": "post_call.recording",
        "semantic_version": 1,
        "execution": {
            "plan_type": "managed_webhook.post_json.v1",
            "connection_id": "00000000-0000-0000-0000-000000000001",
            "mapping_language": "jsonata",
            "mapping_contract_version": 1,
            "mapping_engine": "jsonata-python",
            "mapping_engine_version": "0.7.0",
            "request_mapping": "{'recording': inputs.recording.body}",
            "timeout_seconds": 10,
        },
    }
    document["post_call_actions"] = [action]

    parsed = TenantConfigV3.model_validate(document)

    assert (
        parsed.post_call_actions[0].inputs["recording"].representation == "base64_text"
    )
    with pytest.raises(ValidationError, match="unsupported artifact representation"):
        TenantConfigV3.model_validate(
            {
                **document,
                "post_call_actions": [
                    {
                        **action,
                        "inputs": {
                            "recording": {
                                "artifact": "transcript",
                                "representation": "base64_text",
                            }
                        },
                    }
                ],
            }
        )
    with pytest.raises(ValidationError, match="IDs must be unique"):
        TenantConfigV3.model_validate(
            {**document, "post_call_actions": [action, action]}
        )


def test_v1_rejects_unknown_timezone() -> None:
    document = json.loads(fixture_json())
    document["localization"]["timezone"] = "Mars/Olympus"

    with pytest.raises(ValidationError, match="Unknown IANA timezone"):
        TenantConfigV1.model_validate_json(json.dumps(document))


def test_active_config_serializes_time_and_timezone() -> None:
    active = ActiveTenantConfig.model_validate_json(
        json.dumps(
            {
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "revision_id": "00000000-0000-0000-0000-000000000002",
                "revision_number": 7,
                "published_at": "2026-07-29T12:34:56+02:00",
                "config": json.loads(fixture_json()),
            }
        )
    )

    serialized = json.loads(active.model_dump_json())
    assert serialized["published_at"] == "2026-07-29T12:34:56+02:00"
    assert serialized["config"]["localization"]["timezone"] == "Europe/Bratislava"


def test_conversation_scope_values_are_stable() -> None:
    assert [scope.value for scope in ConversationScope] == ["property_only"]
