import json
import time
from datetime import datetime

import jwt
import pytest
from fastapi import HTTPException
from livekit import api
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.voice_sessions import CreateLiveKitSessionRequest, create_livekit_session
from app.infrastructure.database import Base
from app.infrastructure.models import ConversationModel
from app.tenants.loader import TenantConfigLoader
from app.voice_agent.settings import LiveKitSettings


API_KEY = "devkey"
API_SECRET = "s" * 32


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def configure(monkeypatch):
    monkeypatch.setenv("VOICE_LIVEKIT_ENABLED", "true")
    monkeypatch.setenv("LIVEKIT_API_KEY", API_KEY)
    monkeypatch.setenv("LIVEKIT_API_SECRET", API_SECRET)
    monkeypatch.setenv("LIVEKIT_PUBLIC_URL", "ws://localhost:7880")
    monkeypatch.setenv("LIVEKIT_AGENT_NAME", "hospitality-voice")
    monkeypatch.setenv("VOICE_TURN_DEBUG_OVERRIDES_ENABLED", "false")


def test_livekit_settings_are_optional_until_feature_is_used(monkeypatch):
    monkeypatch.delenv("VOICE_LIVEKIT_ENABLED", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    assert LiveKitSettings.from_env().enabled is False
    with pytest.raises(ValueError):
        LiveKitSettings.from_env().validate_api()


def test_livekit_session_feature_and_configuration_errors(monkeypatch, db):
    monkeypatch.setenv("VOICE_LIVEKIT_ENABLED", "false")
    loader = TenantConfigLoader()
    with pytest.raises(HTTPException) as disabled:
        create_livekit_session(CreateLiveKitSessionRequest(tenant_id="demo_restaurant"), db, loader)
    assert disabled.value.status_code == 403

    monkeypatch.setenv("VOICE_LIVEKIT_ENABLED", "true")
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    with pytest.raises(HTTPException) as missing:
        create_livekit_session(CreateLiveKitSessionRequest(tenant_id="demo_restaurant"), db, loader)
    assert missing.value.status_code == 503


def test_livekit_session_rejects_unknown_tenant(monkeypatch, db):
    configure(monkeypatch)
    with pytest.raises(HTTPException) as error:
        create_livekit_session(CreateLiveKitSessionRequest(tenant_id="missing"), db, TenantConfigLoader())
    assert error.value.status_code == 404


def test_livekit_session_creates_conversation_and_room_scoped_dispatch(monkeypatch, db):
    configure(monkeypatch)
    response = create_livekit_session(
        CreateLiveKitSessionRequest(tenant_id="demo_restaurant"), db, TenantConfigLoader()
    )

    assert response.runtime == "livekit"
    assert response.room_name == f"voice-{response.call_session_id}"
    assert response.livekit_url == "ws://localhost:7880"
    assert db.get(ConversationModel, response.conversation_id).tenant_id == "demo_restaurant"

    claims = api.TokenVerifier(API_KEY, API_SECRET).verify(response.participant_token)
    assert claims.identity == f"browser-{response.call_session_id}"
    assert claims.video.room == response.room_name
    assert claims.video.room_join and claims.video.can_subscribe
    assert claims.video.can_publish_sources == ["microphone"]
    assert claims.video.can_publish_data is False
    dispatch = claims.room_config.agents[0]
    metadata = json.loads(dispatch.metadata)
    assert dispatch.agent_name == "hospitality-voice"
    assert {key: metadata[key] for key in (
        "tenant_id", "call_session_id", "conversation_id", "channel", "language"
    )} == {
        "tenant_id": "demo_restaurant",
        "call_session_id": response.call_session_id,
        "conversation_id": response.conversation_id,
        "channel": "voice",
        "language": "sk",
    }
    assert metadata["turn_config"]["endpointing"]["min_delay_ms"] == 700
    assert response.turn_config.stt_segmentation.threshold == 0.4
    assert metadata["instructions"]
    assert metadata["enabled_capabilities"] == ["reservation.create_request"]
    assert "backend_token" not in metadata
    raw_claims = jwt.decode(response.participant_token, options={"verify_signature": False})
    assert 115 <= raw_claims["exp"] - int(time.time()) <= 120
    serialized = response.model_dump_json()
    assert API_SECRET not in serialized and "ELEVENLABS" not in serialized


def test_livekit_session_accepts_only_same_tenant_conversation(monkeypatch, db):
    configure(monkeypatch)
    now = datetime.now()
    db.add(
        ConversationModel(
            id="existing",
            tenant_id="other",
            channel="voice",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    with pytest.raises(HTTPException) as error:
        create_livekit_session(
            CreateLiveKitSessionRequest(
                tenant_id="demo_restaurant", conversation_id="existing"
            ),
            db,
            TenantConfigLoader(),
        )
    assert error.value.status_code == 404


def test_turn_overrides_are_gated_and_resolved(monkeypatch, db):
    configure(monkeypatch)
    request = CreateLiveKitSessionRequest(
        tenant_id="demo_restaurant",
        turn_overrides={
            "endpointing": {"min_delay_ms": 250},
            "preemptive_generation": {"enabled": True},
        },
    )
    with pytest.raises(HTTPException) as disabled:
        create_livekit_session(request, db, TenantConfigLoader())
    assert disabled.value.status_code == 403

    monkeypatch.setenv("VOICE_TURN_DEBUG_OVERRIDES_ENABLED", "true")
    response = create_livekit_session(request, db, TenantConfigLoader())
    assert response.turn_config.endpointing.min_delay_ms == 250
    assert response.turn_config.preemptive_generation.enabled is True
