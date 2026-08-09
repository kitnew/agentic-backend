from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from app.agent.prompts.loader import PromptLoader
from app.agent.prompts.context import build_agent_context
from app.capabilities.registry import CapabilityRegistry
from app.tenants.loader import TenantConfigInvalidError, TenantConfigLoader


def minimal_config() -> dict:
    return {
        "schema_version": 2,
        "tenant_id": "test",
        "name": "Test Tenant",
        "business_type": "hotel",
        "default_language": "en",
        "locale": "en-GB",
        "supported_locales": ["en-GB"],
        "timezone": "Europe/Bratislava",
        "agent": {"profile": "hotel_assistant"},
        "capabilities": {},
    }


def write_config(tmp_path: Path, config: dict, *, name: str = "test") -> TenantConfigLoader:
    configs_dir = tmp_path / "configs"
    content_dir = tmp_path / "content"
    configs_dir.mkdir()
    content_dir.mkdir()
    (configs_dir / f"{name}.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return TenantConfigLoader(configs_dir, content_dir)


def test_tenant_configs_load():
    loaded = TenantConfigLoader().validate_all(CapabilityRegistry().provider_names())

    assert [tenant.tenant_id for tenant in loaded] == ["demo_restaurant", "penzion_grand"]
    assert loaded[0].voice.stt.provider == "elevenlabs"


def test_penzion_grand_identity_and_rooms():
    tenant = TenantConfigLoader().load("penzion_grand")

    assert tenant.agent.display_name == "Amélia"
    assert tenant.default_locale == "sk-SK"
    assert tenant.supported_locales == ["sk-SK", "en-GB"]
    assert tenant.agent.profile == "hotel_assistant"
    assert [
        (room.code, room.capacity, room.inventory_count, int(room.unit_price_per_night))
        for room in tenant.business_info.room_types
    ] == [
        ("two_bed", 2, 19, 65),
        ("three_bed", 3, 2, 85),
        ("four_bed", 4, 6, 99),
    ]
    assert tenant.business_info.room_types[0].single_occupancy_price == 55


def test_penzion_grand_end_call_policy_requires_explicit_separate_goodbye():
    instructions = TenantConfigLoader().load("penzion_grand").prompt.instructions
    assert "similar acknowledgements are ambiguous" in instructions
    assert "while any tool is pending" in instructions
    assert "wait for a separate, explicit closing statement" in instructions
    assert "active conversation language" in instructions


def test_tenant_config_defaults_voice_disabled_when_omitted(tmp_path: Path):
    config = minimal_config()
    del config["schema_version"]
    del config["supported_locales"]

    loaded = write_config(tmp_path, config).load("test")

    assert loaded.schema_version == 2
    assert loaded.voice.enabled is False


def test_human_handoff_is_configured_per_tenant(tmp_path: Path):
    config = minimal_config()
    config["voice"] = {
        "enabled": True,
        "handoff": True,
        "outbound_dids": ["00 421 900 111 222"],
        "outbound_trunk_id": "ST_outbound",
    }

    loaded = write_config(tmp_path, config).load("test")

    assert loaded.voice.handoff is True
    assert loaded.voice.outbound_dids == ["+421900111222"]
    assert loaded.voice.outbound_trunk_id == "ST_outbound"


def test_enabled_human_handoff_requires_one_destination_and_trunk(tmp_path: Path):
    config = minimal_config()
    config["voice"] = {"handoff": True}

    with pytest.raises(TenantConfigInvalidError, match="exactly one outbound_dids"):
        write_config(tmp_path, config).load("test")


def test_default_locale_must_be_supported(tmp_path: Path):
    config = minimal_config()
    config["supported_locales"] = ["sk-SK"]

    with pytest.raises(TenantConfigInvalidError, match="default locale"):
        write_config(tmp_path, config).load("test")


def test_invalid_timezone_is_rejected(tmp_path: Path):
    config = minimal_config()
    config["timezone"] = "Mars/Olympus"

    with pytest.raises(TenantConfigInvalidError, match="unknown IANA timezone"):
        write_config(tmp_path, config).load("test")


def test_invalid_reservation_cutoff_is_rejected(tmp_path: Path):
    config = minimal_config()
    config["reservation"] = {
        "request_cutoff_local_time": "25:00",
        "cutoff_responses": {"en-GB": "Closed"},
        "new_request_phrases": {"en-GB": ["book a room"]},
    }

    with pytest.raises(TenantConfigInvalidError, match="request_cutoff_local_time"):
        write_config(tmp_path, config).load("test")


def test_duplicate_room_codes_are_rejected(tmp_path: Path):
    config = minimal_config()
    room = {
        "code": "double",
        "display_name": {"en-GB": "Double"},
        "capacity": 2,
        "inventory_count": 1,
        "unit_price_per_night": 50,
        "currency": "EUR",
    }
    config["business_info"] = {"room_types": [room, deepcopy(room)]}

    with pytest.raises(TenantConfigInvalidError, match="room type codes must be unique"):
        write_config(tmp_path, config).load("test")


@pytest.mark.parametrize(
    ("field", "value"),
    [("capacity", -1), ("inventory_count", -1), ("unit_price_per_night", -1)],
)
def test_negative_room_values_are_rejected(tmp_path: Path, field: str, value: int):
    config = minimal_config()
    room = {
        "code": "double",
        "display_name": {"en-GB": "Double"},
        "capacity": 2,
        "inventory_count": 1,
        "unit_price_per_night": 50,
        "currency": "EUR",
    }
    room[field] = value
    config["business_info"] = {"room_types": [room]}

    with pytest.raises(TenantConfigInvalidError, match=field):
        write_config(tmp_path, config).load("test")


def test_invalid_room_currency_is_rejected(tmp_path: Path):
    config = minimal_config()
    config["business_info"] = {
        "room_types": [
            {
                "code": "double",
                "display_name": {"en-GB": "Double"},
                "capacity": 2,
                "inventory_count": 1,
                "unit_price_per_night": 50,
                "currency": "euros",
            }
        ]
    }

    with pytest.raises(TenantConfigInvalidError, match="three-letter code"):
        write_config(tmp_path, config).load("test")


def test_unknown_config_fields_are_rejected(tmp_path: Path):
    config = minimal_config()
    config["unknown_setting"] = True

    with pytest.raises(TenantConfigInvalidError, match="unknown_setting"):
        write_config(tmp_path, config).load("test")


def test_missing_content_file_is_rejected(tmp_path: Path):
    config = minimal_config()
    config["prompt"] = {"instructions_file": "test/missing.md"}

    with pytest.raises(TenantConfigInvalidError, match="does not exist.*test/missing.md"):
        write_config(tmp_path, config).load("test")


@pytest.mark.parametrize(
    ("reference", "message"),
    [("/tmp/instructions.md", "absolute"), ("../instructions.md", "escapes")],
)
def test_external_content_path_is_confined(
    tmp_path: Path, reference: str, message: str
):
    config = minimal_config()
    config["prompt"] = {"instructions_file": reference}

    with pytest.raises(TenantConfigInvalidError, match=message):
        write_config(tmp_path, config).load("test")


def test_duplicate_content_references_are_rejected(tmp_path: Path):
    config = minimal_config()
    config["prompt"] = {
        "knowledge_base_files": ["test/shared.md", "test/shared.md"],
    }

    with pytest.raises(TenantConfigInvalidError, match="duplicate prompt content"):
        write_config(tmp_path, config).load("test")


def test_unsupported_schema_version_is_rejected(tmp_path: Path):
    config = minimal_config()
    config["schema_version"] = 3

    with pytest.raises(TenantConfigInvalidError, match="unsupported schema_version: 3"):
        write_config(tmp_path, config).load("test")


def test_penzion_grand_prompt_contains_each_safe_section_once():
    tenant = TenantConfigLoader().load("penzion_grand")
    context = build_agent_context(tenant, "test-conversation")

    prompt = PromptLoader().build_system_prompt(context)

    assert "You are a business assistant." in prompt
    assert "You are assisting guests of a hotel." in prompt
    assert "You are Amélia" in prompt
    assert '"property_name": "Penzión Grand"' in prompt
    assert "The property has 27 rooms" in prompt
    assert "Every adult requires one normal bed" in prompt
    assert prompt.count("The property has 27 rooms") == 1
    assert "<tenant_identity>" in prompt
    assert "<tenant_business_context>" in prompt
    assert "<tenant_knowledge_base>" in prompt
    assert "<tenant_supplementary_guidance>" not in prompt
    assert "make.com" not in prompt.lower()
    assert "webhook" not in prompt.lower()
    assert "Room availability checks: supported" in prompt
    assert "Current local tenant date and time for this turn" in prompt
    assert "tenant timezone: Europe/Bratislava" in prompt
    assert "Only answer questions related to Penzión Grand" in prompt
    assert "Refuse unrelated requests without answering them" in prompt
    assert "S otázkami mimo Penziónu Grand" in prompt
    assert "I can only help with questions related to Penzión Grand" in prompt
    assert "at or after 22:00" in prompt
    assert "check-out exclusive" in prompt
    assert "check-out date is the departure date" in prompt
    assert "check-in is today or later" in prompt
    assert "reservation.check_availability" not in prompt
    assert "availability_check" not in prompt
    assert "spreadsheet_id" not in prompt
    assert "sheet_name" not in prompt
    assert "1YaOGHsa8lGN9MLJ05z5Hac-l805no23l9mFz8PB4wVI" not in prompt
    assert "submitted requests waiting for staff confirmation" in prompt
    assert "If customer confirmation is required" in prompt
    assert "If confirmation is not required" in prompt
    assert "Do not ask for an email address" in prompt
    assert "first collect only check-in, check-out, requested room type, and room count" in prompt
    assert "immediately call the availability tool in the same response" in prompt
    assert "Collect reservation details only after they agree" in prompt
    assert "Môžem použiť telefónne číslo, z ktorého voláte?" in prompt
    for unavailable_tool in (
        "get_availability",
        "send_reservation_email",
        "send_modification_email",
        "cancel_reservation",
        "check_reservation",
        "transfer_to_number",
    ):
        assert unavailable_tool not in prompt


def test_reservation_order_is_tenant_configured():
    hotel = build_agent_context(
        TenantConfigLoader().load("penzion_grand"), "hotel-conversation"
    )["reservation_policy"]
    restaurant = build_agent_context(
        TenantConfigLoader().load("demo_restaurant"), "restaurant-conversation"
    )["reservation_policy"]

    assert "availability tool in the same response" in hotel
    assert "guest or contact details before" in hotel
    assert "availability tool in the same response" not in restaurant
    assert "guest or contact details before" not in restaurant


def test_prompt_current_time_comes_from_injected_per_turn_clock():
    tenant = TenantConfigLoader().load("penzion_grand")
    context = build_agent_context(
        tenant,
        "test-conversation",
        clock=lambda: datetime(2026, 12, 31, 22, 30, tzinfo=timezone.utc),
    )
    prompt = PromptLoader().build_system_prompt(context)

    assert context["current_local_datetime"] == "2026-12-31T23:30:00+01:00"
    assert "current local datetime: 2026-12-31T23:30:00+01:00" in prompt


def test_tenant_config_rejects_unknown_provider(tmp_path: Path):
    config = minimal_config()
    config["capabilities"] = {
        "reservation.create_request": {
            "enabled": True,
            "provider": "missing_provider",
        }
    }
    loader = write_config(tmp_path, config)

    with pytest.raises(TenantConfigInvalidError, match="Unknown provider"):
        loader.validate_all(CapabilityRegistry().provider_names())
