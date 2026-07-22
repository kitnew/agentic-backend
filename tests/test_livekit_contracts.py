from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.application.livekit_dispatch import resolve_runtime_tools
from app.contracts.livekit import (
    ExecuteLiveKitToolRequest,
    LiveKitJobMetadata,
    PersistLiveKitMessageRequest,
    RuntimeToolDefinition,
)
from app.contracts.voice import VoiceTurnConfig
from app.tenants.loader import TenantConfigLoader


def tool():
    return RuntimeToolDefinition(
        public_name="check_room_availability",
        description="Check availability.",
        backend_capability="reservation.check_availability",
        parameters={
            "type": "object",
            "properties": {"check_in": {"type": "string", "format": "date"}},
            "required": ["check_in"],
            "additionalProperties": False,
        },
    )


def metadata():
    return LiveKitJobMetadata(
        tenant_id="tenant-1",
        call_session_id=str(uuid4()),
        conversation_id=str(uuid4()),
        channel="voice",
        language="sk",
        timezone="Europe/Bratislava",
        instructions="Help the guest.",
        tools=(tool(),),
        stt_language="slk",
        tts_voice_id="voice-1",
        tts_model="model-1",
        tts_language="sk",
        turn_config=VoiceTurnConfig(),
    )


def test_dispatch_contract_round_trip_is_producer_consumer_compatible():
    original = metadata()
    produced = original.model_dump_json()
    consumed = LiveKitJobMetadata.parse_job(produced)
    assert consumed == original
    assert consumed.tools[0].backend_capability == "reservation.check_availability"


def test_contracts_reject_empty_oversized_and_unknown_fields():
    with pytest.raises(ValidationError):
        PersistLiveKitMessageRequest(
            role="user", content=" ", turn_id="turn", item_id="item"
        )
    with pytest.raises(ValidationError):
        PersistLiveKitMessageRequest(
            role="user", content="x" * 32_769, turn_id="turn", item_id="item"
        )
    with pytest.raises(ValidationError):
        ExecuteLiveKitToolRequest(
            capability="reservation.create_request",
            arguments={"payload": "x" * 65_536},
            turn_id="turn",
            tool_call_id="tool",
        )
    with pytest.raises(ValidationError):
        ExecuteLiveKitToolRequest(
            capability="reservation.create_request",
            arguments={},
            turn_id="turn",
            tool_call_id="tool",
            tenant_id="untrusted",
        )
    with pytest.raises(ValidationError):
        RuntimeToolDefinition(
            public_name="bad-name",
            description="bad",
            backend_capability="reservation.create_request",
            parameters={"type": "string", "properties": {}},
        )


def test_backend_resolves_tools_for_every_existing_tenant():
    loader = TenantConfigLoader()
    restaurant = resolve_runtime_tools(loader.load("demo_restaurant"))
    hotel = resolve_runtime_tools(loader.load("penzion_grand"))

    assert [(tool.public_name, tool.backend_capability) for tool in restaurant] == [
        ("create_reservation", "reservation.create_request")
    ]
    assert {tool.backend_capability for tool in hotel} == {
        "reservation.check_availability",
        "reservation.create_request",
        "reservation.change_request",
        "reservation.cancel_request",
    }
    assert next(
        tool for tool in restaurant if tool.backend_capability == "reservation.create_request"
    ).argument_container == "reservation_frame"
    assert next(
        tool for tool in hotel if tool.backend_capability == "reservation.create_request"
    ).argument_container is None

    smoke_loader = TenantConfigLoader(
        Path(__file__).parents[1] / "smoke" / "tenants"
    )
    for tenant_id in ("smoke_manual_a", "smoke_manual_b"):
        assert [
            tool.backend_capability
            for tool in resolve_runtime_tools(smoke_loader.load(tenant_id))
        ] == ["reservation.create_request"]
