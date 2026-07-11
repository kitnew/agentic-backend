import time

import pytest

from app.core.config import AgentRuntimeSettings
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
