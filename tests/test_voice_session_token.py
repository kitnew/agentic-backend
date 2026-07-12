import time

import pytest
from fastapi import HTTPException

from app.api.routes.voice_sessions import CreateVoiceSessionRequest, create_voice_session
from app.core.config import AgentRuntimeSettings
from app.tenants.loader import TenantConfigLoader
from app.voice.session_token import InvalidVoiceSessionToken, VoiceSessionClaims, VoiceSessionTokenCodec


SECRET = "s" * 32


def claims(**changes):
    now = int(time.time())
    values = dict(
        tenant_id="tenant-1",
        call_session_id="call-1",
        conversation_id="conversation-1",
        language="sk",
        timezone="Europe/Bratislava",
        iat=now,
        exp=now + 120,
    )
    values.update(changes)
    return VoiceSessionClaims(**values)


def test_voice_session_token_round_trip_and_tampering():
    codec = VoiceSessionTokenCodec(SECRET)
    token = codec.encode(claims())
    assert codec.decode(token).tenant_id == "tenant-1"
    with pytest.raises(InvalidVoiceSessionToken):
        codec.decode(token[:-1] + ("A" if token[-1] != "A" else "B"))


@pytest.mark.parametrize("token", ["", "one-part", "a.b.c", "!@#.bad"])
def test_voice_session_token_rejects_malformed_values(token):
    with pytest.raises(InvalidVoiceSessionToken):
        VoiceSessionTokenCodec(SECRET).decode(token)


def test_voice_session_token_rejects_expired_and_future_issued_claims():
    codec = VoiceSessionTokenCodec(SECRET)
    now = int(time.time())
    with pytest.raises(InvalidVoiceSessionToken):
        codec.decode(codec.encode(claims(iat=now - 2, exp=now)), now=now)
    with pytest.raises(InvalidVoiceSessionToken):
        codec.decode(codec.encode(claims(iat=now + 1, exp=now + 10)), now=now)


def test_agent_runtime_settings_validation(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_PUBLIC_WS_URL", "ws://runtime.example/api/v1/voice/stream")
    monkeypatch.setenv("VOICE_SESSION_TOKEN_SECRET", SECRET)
    assert AgentRuntimeSettings.from_env().session_token_ttl_seconds == 120
    monkeypatch.setenv("VOICE_SESSION_TOKEN_SECRET", "short")
    with pytest.raises(ValueError):
        AgentRuntimeSettings.from_env()


def test_voice_session_mode_is_signed_and_validated():
    codec = VoiceSessionTokenCodec(SECRET)
    assert codec.decode(codec.encode(claims(mode="call"))).mode == "call"
    with pytest.raises(InvalidVoiceSessionToken):
        codec.decode(codec.encode(claims(mode="full-duplex")))


def test_call_settings_defaults_and_env(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_PUBLIC_WS_URL", "ws://runtime.example/api/v1/voice/stream")
    monkeypatch.setenv("VOICE_SESSION_TOKEN_SECRET", SECRET)
    settings = AgentRuntimeSettings.from_env()
    assert (settings.call_mode_enabled, settings.call_session_ttl_seconds) == (False, 3600)
    monkeypatch.setenv("VOICE_CALL_MODE_ENABLED", "true")
    assert AgentRuntimeSettings.from_env().call_mode_enabled is True


def test_session_issuance_uses_mode_ttl_and_feature_gate(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_PUBLIC_WS_URL", "ws://runtime.example/api/v1/voice/stream")
    monkeypatch.setenv("VOICE_SESSION_TOKEN_SECRET", SECRET)
    loader = TenantConfigLoader()
    manual = create_voice_session(CreateVoiceSessionRequest(tenant_id="demo_restaurant"), db=None, loader=loader)
    manual_claims = VoiceSessionTokenCodec(SECRET).decode(manual.session_token)
    assert (manual.mode, manual_claims.mode, manual_claims.exp - manual_claims.iat) == ("manual", "manual", 120)
    with pytest.raises(HTTPException) as disabled:
        create_voice_session(CreateVoiceSessionRequest(tenant_id="demo_restaurant", mode="call"), db=None, loader=loader)
    assert disabled.value.status_code == 403
    monkeypatch.setenv("VOICE_CALL_MODE_ENABLED", "true")
    call = create_voice_session(CreateVoiceSessionRequest(tenant_id="demo_restaurant", mode="call"), db=None, loader=loader)
    call_claims = VoiceSessionTokenCodec(SECRET).decode(call.session_token)
    assert (call.mode, call_claims.mode, call_claims.exp - call_claims.iat) == ("call", "call", 3600)
