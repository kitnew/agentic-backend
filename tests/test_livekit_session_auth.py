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
STAGING_CREDENTIAL = "staging-access-secret-32-bytes-long"


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


def configure_staging(monkeypatch, *, enabled="true", environment="staging"):
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("LIVEKIT_STAGING_AUTH_ENABLED", enabled)
    monkeypatch.setenv("LIVEKIT_STAGING_AUTH_CREDENTIAL", STAGING_CREDENTIAL)
    monkeypatch.setenv("LIVEKIT_STAGING_ALLOWED_TENANTS", "demo_restaurant")


def test_staging_auth_requires_enabled_feature_and_configured_credential(monkeypatch):
    configure_staging(monkeypatch, enabled="false")
    with pytest.raises(HTTPException) as disabled:
        authenticate_session_access("", "", STAGING_CREDENTIAL)
    assert disabled.value.status_code == 401

    configure_staging(monkeypatch)
    with pytest.raises(HTTPException) as missing:
        authenticate_session_access("", "", "")
    assert missing.value.status_code == 401

    monkeypatch.delenv("LIVEKIT_STAGING_AUTH_CREDENTIAL")
    with pytest.raises(HTTPException) as unconfigured:
        authenticate_session_access("", "", STAGING_CREDENTIAL)
    assert unconfigured.value.status_code == 401


def test_staging_auth_rejects_invalid_credential(monkeypatch):
    configure_staging(monkeypatch)
    with pytest.raises(HTTPException) as invalid:
        authenticate_session_access("", "", "wrong-staging-credential")
    assert invalid.value.status_code == 401


def test_staging_auth_returns_only_allowed_tenants(monkeypatch):
    configure_staging(monkeypatch)
    claims = authenticate_session_access("", "", STAGING_CREDENTIAL)
    assert claims.subject == "staging-debug-chat"
    assert claims.tenant_ids == ("demo_restaurant",)
    assert claims.audience == "livekit-session"
    assert claims.exp - claims.iat == 300


def test_staging_and_debug_auth_are_rejected_in_production(monkeypatch):
    configure_staging(monkeypatch, environment="production")
    with pytest.raises(HTTPException) as staging:
        authenticate_session_access("", "", STAGING_CREDENTIAL)
    assert staging.value.status_code == 401

    monkeypatch.setenv("LIVEKIT_DEBUG_AUTH_ENABLED", "true")
    monkeypatch.setenv("LIVEKIT_DEBUG_ALLOWED_TENANTS", "demo_restaurant")
    with pytest.raises(HTTPException) as debug:
        authenticate_session_access("", "debug-chat", "")
    assert debug.value.status_code == 401


def test_staging_caller_cannot_create_session_for_disallowed_tenant(db):
    now = int(time.time())
    claims = SessionAccessClaims(
        subject="staging-debug-chat",
        tenant_ids=("demo_restaurant",),
        iat=now,
        exp=now + 300,
    )
    with pytest.raises(HTTPException) as forbidden:
        create_livekit_session(
            CreateLiveKitSessionRequest(tenant_id="penzion_grand"),
            db,
            TenantConfigLoader(),
            claims,
        )
    assert forbidden.value.status_code == 403
