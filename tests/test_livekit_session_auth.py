import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.voice_sessions import create_livekit_session
from app.api.session_auth import authenticate_session_access
from app.contracts.livekit import (
    CreateLiveKitSessionRequest,
    SessionAccessClaims,
    SessionAccessTokenCodec,
)
from app.infrastructure.database import Base
from app.tenants.loader import TenantConfigLoader


SECRET = "session-access-secret-32-bytes-long"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def token(*tenant_ids, issued_offset=0, expires_offset=60):
    now = int(time.time())
    return SessionAccessTokenCodec(SECRET).encode(
        SessionAccessClaims(
            subject="caller-1",
            tenant_ids=tenant_ids,
            iat=now + issued_offset,
            exp=now + expires_offset,
        )
    )


def test_session_auth_rejects_missing_malformed_and_expired(monkeypatch):
    monkeypatch.setenv("LIVEKIT_SESSION_AUTH_SECRET", SECRET)
    with pytest.raises(HTTPException) as missing:
        authenticate_session_access("", "")
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as malformed:
        authenticate_session_access("Basic nope", "")
    assert malformed.value.status_code == 401

    with pytest.raises(HTTPException) as expired:
        authenticate_session_access(
            f"Bearer {token('demo_restaurant', issued_offset=-120, expires_offset=-60)}",
            "",
        )
    assert expired.value.status_code == 401


def test_session_auth_returns_authorized_tenants(monkeypatch):
    monkeypatch.setenv("LIVEKIT_SESSION_AUTH_SECRET", SECRET)
    claims = authenticate_session_access(
        f"Bearer {token('demo_restaurant', 'penzion_grand')}", ""
    )
    assert claims.subject == "caller-1"
    assert claims.tenant_ids == ("demo_restaurant", "penzion_grand")


def test_session_creation_rejects_valid_caller_without_tenant_access(db):
    now = int(time.time())
    claims = SessionAccessClaims(
        subject="caller-1", tenant_ids=("demo_restaurant",), iat=now, exp=now + 60
    )
    with pytest.raises(HTTPException) as forbidden:
        create_livekit_session(
            CreateLiveKitSessionRequest(tenant_id="penzion_grand"),
            db,
            TenantConfigLoader(),
            claims,
        )
    assert forbidden.value.status_code == 403


def test_debug_auth_is_explicit_and_development_only(monkeypatch):
    monkeypatch.setenv("LIVEKIT_DEBUG_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "LIVEKIT_DEBUG_ALLOWED_TENANTS", "demo_restaurant,penzion_grand"
    )
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(HTTPException) as production:
        authenticate_session_access("", "debug-chat")
    assert production.value.status_code == 401
    assert "LIVEKIT_DEBUG_AUTH_ENABLED=true" in production.value.detail

    monkeypatch.setenv("APP_ENV", "development")
    claims = authenticate_session_access("", "debug-chat")
    assert claims.subject == "debug-chat"
    assert claims.tenant_ids == ("demo_restaurant", "penzion_grand")
