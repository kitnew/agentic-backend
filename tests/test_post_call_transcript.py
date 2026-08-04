import asyncio
from datetime import datetime
from threading import Lock
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.application.call_finalization import (
    finalize_call,
    format_elevenlabs_transcript,
    format_transcript,
)
from app.domain.call_sessions.entities import CallSession
from app.domain.call_sessions.enums import CallFinalizationStatus, CallSessionStatus
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageRole, MessageStatus
from app.infrastructure.database import Base
from app.infrastructure.repositories.call_session_repository import CallSessionRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.integrations.google_sheets.schemas import GoogleSheetsAppendRowResult
from app.integrations.post_call_webhook import send_post_call_webhook


class Summary:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    async def summarize(self, transcript):
        self.calls += 1
        await asyncio.sleep(0)
        if self.error:
            error, self.error = self.error, None
            raise error
        return "Hosť požiadal o izbu. Žiadosť bola odoslaná."


class Sheets:
    def __init__(self):
        self.keys = set()
        self.rows = []
        self.lock = Lock()

    def append_row_once(self, request, *, idempotency_key):
        with self.lock:
            if idempotency_key in self.keys:
                return GoogleSheetsAppendRowResult(
                    spreadsheet_id=request.spreadsheet_id,
                    sheet_name=request.sheet_name,
                    updated_rows=0,
                )
            self.keys.add(idempotency_key)
            self.rows.append(request)
            return GoogleSheetsAppendRowResult(
                spreadsheet_id=request.spreadsheet_id,
                sheet_name=request.sheet_name,
                updated_range="Transkripty!A2:D2",
                updated_rows=1,
            )


def seed(db):
    now = datetime(2026, 7, 22, 20, 15)
    call = CallSession(
        id="call-1",
        tenant_id="penzion_grand",
        conversation_id="conversation-1",
        livekit_room_name="voice-call-1",
        caller_phone="+421900111222",
        status=CallSessionStatus.COMPLETED,
        finalization_status=CallFinalizationStatus.PENDING,
        started_at=now,
        ended_at=now,
        updated_at=now,
    )
    CallSessionRepository(db).create(call)
    for item in (
        Message(
            id="user-1", tenant_id="penzion_grand", conversation_id="conversation-1",
            channel="voice", role=MessageRole.USER, content="  Dobrý deň,\nchcem izbu. ",
            status=MessageStatus.PROCESSED, metadata={"call_session_id": "call-1"},
            created_at=now, processed_at=now,
        ),
        Message(
            id="assistant-interrupted", tenant_id="penzion_grand", conversation_id="conversation-1",
            channel="voice", role=MessageRole.ASSISTANT, content="Nedokončená odpoveď",
            status=MessageStatus.PROCESSED,
            metadata={"call_session_id": "call-1", "interrupted": True},
            created_at=now, processed_at=now,
        ),
        Message(
            id="assistant-1", tenant_id="penzion_grand", conversation_id="conversation-1",
            channel="voice", role=MessageRole.ASSISTANT, content="Žiadosť bola odoslaná.",
            status=MessageStatus.PROCESSED,
            metadata={"call_session_id": "call-1", "interrupted": False},
            created_at=now, processed_at=now,
        ),
    ):
        MessageRepository(db).save(item)
    return call


def test_transcript_uses_only_final_persisted_messages():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed(db)
        assert format_transcript(MessageRepository(db).list_by_conversation_id("conversation-1")) == (
            "Hosť: Dobrý deň, chcem izbu.\nAgent: Žiadosť bola odoslaná."
        )


def test_elevenlabs_transcript_maps_roles_and_excludes_non_messages():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed(db)
        messages = MessageRepository(db).list_by_conversation_id("conversation-1")
        messages.extend(
            [
                Message(
                    id="system-1", tenant_id="penzion_grand", conversation_id="conversation-1",
                    channel="voice", role=MessageRole.SYSTEM, content="system prompt",
                    status=MessageStatus.PROCESSED, metadata={"call_session_id": "call-1"},
                    created_at=datetime(2026, 7, 22, 20, 16),
                ),
                Message(
                    id="tool-1", tenant_id="penzion_grand", conversation_id="conversation-1",
                    channel="voice", role=MessageRole.TOOL, content="tool result",
                    status=MessageStatus.PROCESSED, metadata={"call_session_id": "call-1"},
                    created_at=datetime(2026, 7, 22, 20, 17),
                ),
                Message(
                    id="empty-1", tenant_id="penzion_grand", conversation_id="conversation-1",
                    channel="voice", role=MessageRole.USER, content="  \n",
                    status=MessageStatus.PROCESSED, metadata={"call_session_id": "call-1"},
                    created_at=datetime(2026, 7, 22, 20, 18),
                ),
            ]
        )
        assert format_elevenlabs_transcript(messages) == [
            {"role": "user", "message": "Dobrý deň, chcem izbu."},
            {"role": "agent", "message": "Žiadosť bola odoslaná."},
        ]


def test_finalization_maps_row_preserves_phone_and_is_idempotent():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sheets, summary = Sheets(), Summary()
    with Session(engine) as db:
        seed(db)
        first = asyncio.run(finalize_call(db, "call-1", summary_client=summary, sheets=sheets))
        second = asyncio.run(finalize_call(db, "call-1", summary_client=summary, sheets=sheets))
        call = CallSessionRepository(db).get("call-1")
    assert first == second
    assert summary.calls == 1 and len(sheets.rows) == 1
    assert sheets.rows[0].values == [
        "Hosť: Dobrý deň, chcem izbu.\nAgent: Žiadosť bola odoslaná.",
        "Hosť požiadal o izbu. Žiadosť bola odoslaná.",
        "22.07.2026 22:15:00",
        "+421900111222",
    ]
    assert call.finalization_status == CallFinalizationStatus.COMPLETED


def test_failed_finalization_can_be_retried():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    summary, sheets = Summary(RuntimeError("llm down")), Sheets()
    with Session(engine) as db:
        seed(db)
        try:
            asyncio.run(finalize_call(db, "call-1", summary_client=summary, sheets=sheets))
        except RuntimeError:
            pass
        assert CallSessionRepository(db).get("call-1").finalization_status == CallFinalizationStatus.FAILED
        asyncio.run(finalize_call(db, "call-1", summary_client=summary, sheets=sheets))
        assert CallSessionRepository(db).get("call-1").finalization_status == CallFinalizationStatus.COMPLETED
    assert len(sheets.rows) == 1


def test_concurrent_finalization_attempts_append_one_row(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'calls.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        seed(db)
    sheets, summary = Sheets(), Summary()

    async def run_one():
        with sessions() as db:
            return await finalize_call(db, "call-1", summary_client=summary, sheets=sheets)

    async def run_both():
        return await asyncio.gather(run_one(), run_one())

    asyncio.run(run_both())
    assert len(sheets.rows) == 1


class RecordingEgress:
    async def list_egress(self, _request):
        return SimpleNamespace(
            items=[SimpleNamespace(status="EGRESS_COMPLETE", error="", details="")]
        )


class RecordingClient:
    def __init__(self):
        self.egress = RecordingEgress()


class WebhookResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class WebhookSession:
    def __init__(self):
        self.calls = []

    def post(self, url, *, json, headers):
        self.calls.append((url, json, headers))
        return WebhookResponse()


def test_post_call_events_use_same_webhook_with_distinct_idempotency_keys(monkeypatch):
    monkeypatch.setenv("POST_CALL_WEBHOOK_KEY", "test-key")
    config = SimpleNamespace(
        webhook_url="https://make.example.test/post-call",
        webhook_api_key_env="POST_CALL_WEBHOOK_KEY",
    )
    session = WebhookSession()
    for event_type in ("post_call_transcription", "post_call_audio"):
        asyncio.run(
            send_post_call_webhook(
                config,
                {
                    "type": event_type,
                    "data": {"conversation_id": "conversation-1"},
                },
                session=session,
            )
        )

    assert [call[0] for call in session.calls] == [config.webhook_url] * 2
    assert [call[2]["Idempotency-Key"] for call in session.calls] == [
        "post-call:conversation-1:post_call_transcription",
        "post-call:conversation-1:post_call_audio",
    ]
    assert all(call[2]["x-make-apikey"] == "test-key" for call in session.calls)


def test_finalization_sends_separate_base64_events_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVEKIT_RECORDING_DIR", str(tmp_path))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sent = []

    async def send(config, payload):
        sent.append(payload)

    config = SimpleNamespace(
        spreadsheet_id="sheet",
        sheet_name="transcripts",
        webhook_url="https://make.example.test/post-call",
        webhook_api_key_env=None,
        recording_delivery_mode="base64",
        recording_public_base_url=None,
    )
    tenant = SimpleNamespace(
        timezone="Europe/Bratislava",
        name="Penzión Grand",
        agent=SimpleNamespace(profile="hotel_assistant", display_name="Amélia"),
        post_call_transcript=config,
    )
    with Session(engine) as db:
        seed(db)
        call = CallSessionRepository(db).get("call-1")
        call.recording_egress_id = "egress-1"
        CallSessionRepository(db).save(call)
        Path(tmp_path, "call-1.ogg").write_bytes(b"recorded audio")
        sheets = Sheets()
        first = asyncio.run(
            finalize_call(
                db,
                "call-1",
                summary_client=Summary(),
                sheets=sheets,
                tenant_loader=SimpleNamespace(load=lambda _tenant_id: tenant),
                recording_client=RecordingClient(),
                webhook_sender=send,
            )
        )
        second = asyncio.run(
            finalize_call(
                db,
                "call-1",
                summary_client=Summary(),
                sheets=sheets,
                tenant_loader=SimpleNamespace(load=lambda _tenant_id: tenant),
                recording_client=RecordingClient(),
                webhook_sender=send,
            )
        )
    assert first == second
    assert [payload["type"] for payload in sent] == [
        "post_call_transcription",
        "post_call_audio",
    ]
    transcription, audio = sent
    assert transcription["data"]["analysis"]["transcript_summary"]
    assert transcription["data"]["transcript"] == [
        {"role": "user", "message": "Dobrý deň, chcem izbu."},
        {"role": "agent", "message": "Žiadosť bola odoslaná."},
    ]
    assert transcription["data"]["conversation_initiation_client_data"]["dynamic_variables"]["system__time"] == "2026-07-22T20:15:00"
    assert transcription["data"]["user_id"] == "+421900111222"
    assert transcription["data"]["conversation_id"] == "conversation-1"
    assert audio["data"]["conversation_id"] == "conversation-1"
    assert audio["data"]["user_id"] == "+421900111222"
    assert audio["data"]["agent_id"] == "hotel_assistant"
    assert audio["data"]["agent_name"] == "Amélia"
    assert audio["data"]["full_audio"] == "cmVjb3JkZWQgYXVkaW8="
    with Session(engine) as db:
        call = CallSessionRepository(db).get("call-1")
    assert call.post_call_transcription_sent is True
    assert call.post_call_audio_sent is True


def test_finalization_uses_recording_url_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVEKIT_RECORDING_DIR", str(tmp_path))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sent = []

    async def send(_config, payload):
        sent.append(payload)

    config = SimpleNamespace(
        spreadsheet_id="sheet",
        sheet_name="transcripts",
        webhook_url="https://make.example.test/post-call",
        webhook_api_key_env=None,
        recording_delivery_mode="recording_url",
        recording_public_base_url="https://records.example.test/calls",
    )
    tenant = SimpleNamespace(timezone="Europe/Bratislava", post_call_transcript=config)
    with Session(engine) as db:
        seed(db)
        call = CallSessionRepository(db).get("call-1")
        call.recording_egress_id = "egress-1"
        CallSessionRepository(db).save(call)
        Path(tmp_path, "call-1.ogg").write_bytes(b"recorded audio")
        asyncio.run(
            finalize_call(
                db,
                "call-1",
                summary_client=Summary(),
                sheets=Sheets(),
                tenant_loader=SimpleNamespace(load=lambda _tenant_id: tenant),
                recording_client=RecordingClient(),
                webhook_sender=send,
            )
        )
    assert sent[0]["type"] == "post_call_transcription"
    assert sent[1]["type"] == "post_call_audio"
    assert sent[1]["data"]["recording_url"] == "https://records.example.test/calls/call-1.ogg"


def test_recording_failure_marks_finalization_failed_without_webhook(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVEKIT_RECORDING_DIR", str(tmp_path))
    monkeypatch.setenv("LIVEKIT_RECORDING_TIMEOUT_SECONDS", "0.01")
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sent = []

    async def send(_config, payload):
        sent.append(payload)

    config = SimpleNamespace(
        spreadsheet_id="sheet",
        sheet_name="transcripts",
        webhook_url="https://make.example.test/post-call",
        webhook_api_key_env=None,
        recording_delivery_mode="base64",
        recording_public_base_url=None,
    )
    tenant = SimpleNamespace(timezone="Europe/Bratislava", post_call_transcript=config)
    class ActiveEgress:
        async def list_egress(self, _request):
            return SimpleNamespace(items=[SimpleNamespace(status="EGRESS_ACTIVE")])

    with Session(engine) as db:
        seed(db)
        call = CallSessionRepository(db).get("call-1")
        call.recording_egress_id = "egress-1"
        CallSessionRepository(db).save(call)
        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(
                finalize_call(
                    db,
                    "call-1",
                    summary_client=Summary(),
                    sheets=Sheets(),
                    tenant_loader=SimpleNamespace(load=lambda _tenant_id: tenant),
                    recording_client=SimpleNamespace(egress=ActiveEgress()),
                    webhook_sender=send,
                )
            )
        assert CallSessionRepository(db).get("call-1").finalization_status == CallFinalizationStatus.FAILED
    assert [payload["type"] for payload in sent] == ["post_call_transcription"]


def test_failed_event_does_not_suppress_other_event_and_retry_is_per_event(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVEKIT_RECORDING_DIR", str(tmp_path))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    attempted = []
    fail_transcription = True

    async def send(_config, payload):
        nonlocal fail_transcription
        attempted.append(payload["type"])
        if payload["type"] == "post_call_transcription" and fail_transcription:
            fail_transcription = False
            raise RuntimeError("transcription unavailable")

    config = SimpleNamespace(
        spreadsheet_id="sheet",
        sheet_name="transcripts",
        webhook_url="https://make.example.test/post-call",
        webhook_api_key_env=None,
        recording_delivery_mode="base64",
        recording_public_base_url=None,
    )
    tenant = SimpleNamespace(timezone="Europe/Bratislava", post_call_transcript=config)
    with Session(engine) as db:
        seed(db)
        call = CallSessionRepository(db).get("call-1")
        call.recording_egress_id = "egress-1"
        CallSessionRepository(db).save(call)
        Path(tmp_path, "call-1.ogg").write_bytes(b"recorded audio")
        with pytest.raises(RuntimeError, match="transcription unavailable"):
            asyncio.run(
                finalize_call(
                    db,
                    "call-1",
                    summary_client=Summary(),
                    sheets=Sheets(),
                    tenant_loader=SimpleNamespace(load=lambda _tenant_id: tenant),
                    recording_client=RecordingClient(),
                    webhook_sender=send,
                )
            )
        asyncio.run(
            finalize_call(
                db,
                "call-1",
                summary_client=Summary(),
                sheets=Sheets(),
                tenant_loader=SimpleNamespace(load=lambda _tenant_id: tenant),
                recording_client=RecordingClient(),
                webhook_sender=send,
            )
        )
        call = CallSessionRepository(db).get("call-1")
    assert attempted == [
        "post_call_transcription",
        "post_call_audio",
        "post_call_transcription",
    ]
    assert call.post_call_transcription_sent is True
    assert call.post_call_audio_sent is True
