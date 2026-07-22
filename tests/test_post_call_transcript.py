import asyncio
from datetime import datetime
from threading import Lock
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.application.call_finalization import finalize_call, format_transcript
from app.domain.call_sessions.entities import CallSession
from app.domain.call_sessions.enums import CallFinalizationStatus, CallSessionStatus
from app.domain.messages.entities import Message
from app.domain.messages.enums import MessageRole, MessageStatus
from app.infrastructure.database import Base
from app.infrastructure.repositories.call_session_repository import CallSessionRepository
from app.infrastructure.repositories.message_repository import MessageRepository
from app.integrations.google_sheets.schemas import GoogleSheetsAppendRowResult


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
