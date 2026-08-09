import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
import yaml
from fastapi import HTTPException
from livekit import rtc
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.voice_sessions import (
    _authenticate_livekit_bootstrap,
    bootstrap_inbound_livekit_session,
)
from app.contracts.livekit import (
    InboundSipBootstrapRequest,
    LiveKitBootstrapClaims,
    LiveKitBackendTokenCodec,
)
from app.core.config import InboundSipSettings
from app.infrastructure.database import Base
from app.infrastructure.models import CallSessionModel, ConversationModel
from app.tenants.loader import TenantConfigInvalidError, TenantConfigLoader
from app.tenants.schemas import normalize_phone_number
from app.voice_agent.server import build_inbound_bootstrap_request


SECRET = "voice-bootstrap-secret-at-least-32-bytes"
SOURCE_CONFIG = Path("app/tenants/configs/demo_restaurant.yaml")


def tenant_loader(tmp_path, *assignments):
    raw = yaml.safe_load(SOURCE_CONFIG.read_text())
    for tenant_id, did in assignments:
        config = dict(raw)
        config["tenant_id"] = tenant_id
        config["name"] = tenant_id
        config["voice"] = dict(raw["voice"], inbound_dids=[did])
        (tmp_path / f"{tenant_id}.yaml").write_text(yaml.safe_dump(config))
    return TenantConfigLoader(configs_dir=tmp_path)


def configure(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("INBOUND_SIP_ENABLED", "true")
    monkeypatch.setenv("LIVEKIT_INTERNAL_URL", "ws://livekit:7880")
    monkeypatch.setenv("LIVEKIT_REDIS_ADDRESS", "redis:6379")
    monkeypatch.setenv("LIVEKIT_SIP_EXTERNAL_IP", "8.8.8.8")
    monkeypatch.setenv("LIVEKIT_SIP_DOMAIN", "sip.example.test")
    monkeypatch.setenv("VOICE_SESSION_TOKEN_SECRET", SECRET)
    monkeypatch.setenv("LIVEKIT_BACKEND_TOKEN_TTL_SECONDS", "300")


def request(called_number="+12025550123"):
    return InboundSipBootstrapRequest(
        room_name="sip-call-1",
        participant_identity="sip-participant-1",
        sip_call_id="livekit-call-1",
        sip_call_id_full="carrier-call-1",
        sip_trunk_id="trunk-1",
        sip_rule_id="rule-1",
        caller_number="+12025550100",
        called_number=called_number,
    )


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_sip_configuration_is_optional_locally_and_fails_fast_when_incomplete(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("INBOUND_SIP_ENABLED", "false")
    InboundSipSettings.from_env().validate()

    monkeypatch.setenv("INBOUND_SIP_ENABLED", "true")
    with pytest.raises(ValueError, match="staging or production"):
        InboundSipSettings.from_env().validate()

    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(ValueError, match="EXTERNAL_IP"):
        InboundSipSettings.from_env().validate()


def test_api_startup_rejects_enabled_sip_without_tenant_did(monkeypatch):
    from app.main import lifespan

    configure(monkeypatch)
    monkeypatch.setattr(
        TenantConfigLoader,
        "validate_all",
        lambda self, provider_names: [
            SimpleNamespace(voice=SimpleNamespace(inbound_dids=()))
        ],
    )

    async def start():
        async with lifespan(SimpleNamespace()):
            pass

    with pytest.raises(ValueError, match="at least one configured tenant DID"):
        asyncio.run(start())


def test_did_normalization_and_duplicate_assignment_validation(tmp_path):
    assert normalize_phone_number("00 1 (202) 555-0123") == "+12025550123"
    assert normalize_phone_number("+1 202-555-0123") == "+12025550123"
    with pytest.raises(ValueError):
        normalize_phone_number("not-a-number")

    loader = tenant_loader(
        tmp_path,
        ("tenant_a", "+1 202 555 0123"),
        ("tenant_b", "0012025550123"),
    )
    with pytest.raises(TenantConfigInvalidError, match="assigned to both"):
        loader.validate_all({"calculator", "google_sheets", "disabled"})


def test_bootstrap_authentication_rejects_missing_and_accepts_service_token(monkeypatch):
    monkeypatch.setenv("VOICE_SESSION_TOKEN_SECRET", SECRET)
    with pytest.raises(HTTPException) as missing:
        _authenticate_livekit_bootstrap("")
    assert missing.value.status_code == 401

    now = int(time.time())
    token = LiveKitBackendTokenCodec(SECRET).encode_bootstrap(
        LiveKitBootstrapClaims(iat=now, exp=now + 60)
    )
    claims = _authenticate_livekit_bootstrap(f"Bearer {token}")
    assert claims.audience == "livekit-inbound-bootstrap"


def test_bootstrap_resolves_did_and_reuses_one_durable_session(
    monkeypatch, tmp_path, db
):
    configure(monkeypatch)
    loader = tenant_loader(tmp_path, ("tenant_a", "+12025550123"))
    claims = LiveKitBootstrapClaims(iat=int(time.time()), exp=int(time.time()) + 60)

    first = bootstrap_inbound_livekit_session(request(), db, loader, claims)
    second = bootstrap_inbound_livekit_session(request(), db, loader, claims)

    assert first.tenant_id == "tenant_a"
    assert first.call_session_id == second.call_session_id
    assert first.conversation_id == second.conversation_id
    assert first.reused is False and second.reused is True
    assert first.job_metadata.origin == "sip"
    backend_claims = LiveKitBackendTokenCodec(SECRET).decode(first.backend_token)
    assert backend_claims.tenant_id == "tenant_a"
    assert backend_claims.call_session_id == first.call_session_id
    assert db.query(CallSessionModel).count() == 1
    assert db.query(ConversationModel).count() == 1
    call = db.get(CallSessionModel, first.call_session_id)
    assert call.sip_call_key == "full:carrier-call-1"
    assert call.livekit_room_name == "sip-call-1"
    assert call.sip_participant_identity == "sip-participant-1"
    assert call.tenant_id == "tenant_a"


def test_bootstrap_carries_tenant_handoff_config_to_job_metadata(monkeypatch, tmp_path, db):
    configure(monkeypatch)
    tenant_loader(tmp_path, ("tenant_a", "+12025550123"))
    config_path = tmp_path / "tenant_a.yaml"
    config = yaml.safe_load(config_path.read_text())
    config["voice"].update(
        {
            "handoff": True,
            "outbound_dids": ["+421900111222"],
            "outbound_trunk_id": "ST_outbound",
        }
    )
    config_path.write_text(yaml.safe_dump(config))
    loader = TenantConfigLoader(configs_dir=tmp_path)
    claims = LiveKitBootstrapClaims(iat=int(time.time()), exp=int(time.time()) + 60)

    response = bootstrap_inbound_livekit_session(request(), db, loader, claims)

    assert response.job_metadata.handoff is True
    assert response.job_metadata.outbound_dids == ("+421900111222",)
    assert response.job_metadata.outbound_trunk_id == "ST_outbound"


def test_concurrent_bootstrap_returns_one_session(monkeypatch, tmp_path):
    configure(monkeypatch)
    tenant_loader(tmp_path, ("tenant_a", "+12025550123"))
    engine = create_engine(
        f"sqlite:///{tmp_path / 'inbound.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    barrier = Barrier(2)

    def bootstrap():
        with sessions() as db:
            barrier.wait()
            response = bootstrap_inbound_livekit_session(
                request(),
                db,
                TenantConfigLoader(configs_dir=tmp_path),
                LiveKitBootstrapClaims(
                    iat=int(time.time()), exp=int(time.time()) + 60
                ),
            )
            return response.call_session_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        call_ids = list(pool.map(lambda _index: bootstrap(), range(2)))

    assert len(set(call_ids)) == 1
    with sessions() as db:
        assert db.query(CallSessionModel).count() == 1
        assert db.query(ConversationModel).count() == 1


def test_bootstrap_rejects_unknown_number_without_creating_state(
    monkeypatch, tmp_path, db
):
    configure(monkeypatch)
    loader = tenant_loader(tmp_path, ("tenant_a", "+12025550123"))
    claims = LiveKitBootstrapClaims(iat=int(time.time()), exp=int(time.time()) + 60)

    with pytest.raises(HTTPException) as unknown:
        bootstrap_inbound_livekit_session(
            request(called_number="+12025550999"), db, loader, claims
        )
    assert unknown.value.status_code == 404
    assert db.query(CallSessionModel).count() == 0
    assert db.query(ConversationModel).count() == 0


def test_bootstrap_rejects_unexpected_trunk_without_creating_state(
    monkeypatch, tmp_path, db
):
    configure(monkeypatch)
    monkeypatch.setenv("LIVEKIT_SIP_EXPECTED_TRUNK_ID", "expected-trunk")
    loader = tenant_loader(tmp_path, ("tenant_a", "+12025550123"))
    claims = LiveKitBootstrapClaims(iat=int(time.time()), exp=int(time.time()) + 60)

    with pytest.raises(HTTPException) as unexpected:
        bootstrap_inbound_livekit_session(request(), db, loader, claims)
    assert unexpected.value.status_code == 403
    assert db.query(CallSessionModel).count() == 0
    assert db.query(ConversationModel).count() == 0


def test_bootstrap_rejects_disabled_tenant_without_creating_state(
    monkeypatch, tmp_path, db
):
    configure(monkeypatch)
    tenant_loader(tmp_path, ("tenant_a", "+12025550123"))
    path = tmp_path / "tenant_a.yaml"
    config = yaml.safe_load(path.read_text())
    config["enabled"] = False
    path.write_text(yaml.safe_dump(config))
    claims = LiveKitBootstrapClaims(iat=int(time.time()), exp=int(time.time()) + 60)

    with pytest.raises(HTTPException) as disabled:
        bootstrap_inbound_livekit_session(
            request(), db, TenantConfigLoader(configs_dir=tmp_path), claims
        )
    assert disabled.value.status_code == 404
    assert db.query(CallSessionModel).count() == 0
    assert db.query(ConversationModel).count() == 0


def test_sip_attributes_are_normalized_for_backend_bootstrap():
    participant = SimpleNamespace(
        identity="sip-user",
        attributes={
            "sip.callID": "lk-call",
            "sip.callIDFull": "carrier-call",
            "sip.phoneNumber": "00 1 (202) 555-0100",
            "sip.trunkPhoneNumber": "+1 202-555-0123",
            "sip.trunkID": "trunk",
            "sip.ruleID": "rule",
        },
    )
    normalized = build_inbound_bootstrap_request("sip-room", participant)
    assert normalized.caller_number == "+12025550100"
    assert normalized.called_number == "+12025550123"
    assert normalized.sip_call_key == "full:carrier-call"


def test_sip_bootstrap_failure_does_not_start_agent(monkeypatch):
    from app.voice_agent import server as voice_server

    started = False

    class FailingBackend:
        def __init__(self, *_args):
            pass

        async def bootstrap_inbound(self, _request):
            raise RuntimeError("backend unavailable")

        async def aclose(self):
            pass

    class Context:
        job = SimpleNamespace(metadata="")
        room = SimpleNamespace(name="sip-room")

        async def connect(self, **_kwargs):
            pass

        async def wait_for_participant(self):
            return SimpleNamespace(
                kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
                identity="sip-user",
                attributes={
                    "sip.callIDFull": "carrier-call",
                    "sip.phoneNumber": "+12025550100",
                    "sip.trunkPhoneNumber": "+12025550123",
                    "sip.trunkID": "trunk",
                    "sip.ruleID": "rule",
                },
            )

    def forbidden(*_args):
        nonlocal started
        started = True
        raise AssertionError("AgentSession must not be built")

    monkeypatch.setattr(voice_server, "BackendCoreClient", FailingBackend)
    monkeypatch.setattr(voice_server, "build_session", forbidden)
    monkeypatch.setattr(
        voice_server,
        "settings",
        SimpleNamespace(
            session_token_secret=SECRET,
            backend_token_ttl_seconds=60,
            backend_url="http://backend",
        ),
    )
    asyncio.run(voice_server.voice_agent(Context()))
    assert started is False
