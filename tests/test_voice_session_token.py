import time

import pytest

from app.contracts.livekit import (
    InvalidLiveKitBackendToken,
    LiveKitBackendClaims,
    LiveKitBackendTokenCodec,
)


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
    return LiveKitBackendClaims(**values)


def test_livekit_backend_token_round_trip_and_tampering():
    codec = LiveKitBackendTokenCodec(SECRET)
    token = codec.encode(claims())
    assert codec.decode(token).tenant_id == "tenant-1"
    with pytest.raises(InvalidLiveKitBackendToken):
        codec.decode(token[:-1] + ("A" if token[-1] != "A" else "B"))


@pytest.mark.parametrize("token", ["", "one-part", "a.b.c", "!@#.bad"])
def test_livekit_backend_token_rejects_malformed_values(token):
    with pytest.raises(InvalidLiveKitBackendToken):
        LiveKitBackendTokenCodec(SECRET).decode(token)


def test_livekit_backend_token_rejects_expired_and_future_claims():
    codec = LiveKitBackendTokenCodec(SECRET)
    now = int(time.time())
    with pytest.raises(InvalidLiveKitBackendToken):
        codec.decode(codec.encode(claims(iat=now - 2, exp=now)), now=now)
    with pytest.raises(InvalidLiveKitBackendToken):
        codec.decode(codec.encode(claims(iat=now + 1, exp=now + 10)), now=now)
    with pytest.raises(InvalidLiveKitBackendToken):
        codec.decode(codec.encode(claims(tenant_id=123)), now=now)
