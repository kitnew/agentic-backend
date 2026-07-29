import json
from pathlib import Path

import pytest
from contracts import (
    ActiveTenantConfig,
    ConversationScope,
    TenantConfigV1,
    TenantConfigV2,
)
from pydantic import ValidationError

FIXTURE = Path(__file__).parent / "fixtures" / "tenant_config_v1.json"
V2_FIXTURE = Path(__file__).parent / "fixtures" / "tenant_config_v2.json"


def fixture_json() -> str:
    return FIXTURE.read_text()


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
