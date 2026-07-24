import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.voice_sessions import (
    execute_livekit_tool,
    finalize_livekit_call,
    persist_livekit_message,
)
from app.main import app
from app.contracts.livekit import (
    ExecuteLiveKitToolRequest,
    FinalizeLiveKitCallRequest,
    LiveKitBackendClaims,
    PersistLiveKitMessageRequest,
)
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityExecutionResult, CapabilityExecutionStatus
from app.domain.tool_calls.entities import ToolCall
from app.domain.tool_calls.enums import ToolCallStatus
from app.infrastructure.database import Base
from app.infrastructure.models import CallSessionModel, MessageModel, ToolCallModel
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository
from app.tenants.loader import TenantConfigLoader


def claims(
    tenant_id="demo_restaurant",
    call_session_id="call-1",
    conversation_id="conversation-1",
):
    now = int(time.time())
    return LiveKitBackendClaims(
        tenant_id=tenant_id,
        call_session_id=call_session_id,
        conversation_id=conversation_id,
        language="sk",
        timezone="Europe/Bratislava",
        iat=now,
        exp=now + 60,
    )


class Executor:
    def __init__(self):
        self.commands = []

    async def execute(self, command):
        self.commands.append(command)
        return CapabilityExecutionResult(
            command_id=command.command_id,
            status=CapabilityExecutionStatus.SUCCESS,
            result={"accepted": True},
            execution_duration_ms=1,
        )

    async def enqueue(self, command):
        self.commands.append(command)
        return "1-0"


def active_call(
    db,
    *,
    tenant_id="demo_restaurant",
    call_session_id="call-1",
    conversation_id="conversation-1",
    status="active",
    finalization_status="pending",
):
    now = __import__("datetime").datetime.now()
    db.add(
        CallSessionModel(
            id=call_session_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            livekit_room_name=f"voice-{call_session_id}",
            status=status,
            finalization_status=finalization_status,
            started_at=now,
            updated_at=now,
        )
    )
    db.commit()


def test_voice_messages_are_idempotent_and_preserve_interruption_state():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        active_call(db)
        request = PersistLiveKitMessageRequest(
            role="assistant",
            content="partial",
            turn_id="turn-1",
            item_id="assistant-1",
            interrupted=True,
        )
        first = persist_livekit_message(request, claims(), db)
        second = persist_livekit_message(request, claims(), db)
        assert first == second
        assert db.query(MessageModel).count() == 1
        assert db.query(MessageModel).one().extra_metadata["interrupted"] is True


def test_native_tool_routes_through_backend_capability_executor_with_correlation():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    executor = Executor()
    with Session(engine) as db:
        active_call(db)
        persist_livekit_message(
            PersistLiveKitMessageRequest(
                role="user",
                content="Book for two",
                turn_id="turn-1",
                item_id="turn-1",
            ),
            claims(),
            db,
        )
        request = ExecuteLiveKitToolRequest(
            capability="reservation.create_request",
            arguments={
                "reservation_frame": {
                    "guest_name": "Nina",
                    "date": "2026-08-01",
                    "time": "19:00",
                    "party_size": 2,
                    "phone": "+421900000000",
                }
            },
            turn_id="turn-1",
            tool_call_id="tool-1",
        )
        result = asyncio.run(
            execute_livekit_tool(
                request,
                claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )
        command = executor.commands[0]
        assert result.status == "success"
        assert command.tenant_id == "demo_restaurant"
        assert command.conversation_id == "conversation-1"
        assert command.call_session_id == "call-1"
        assert command.idempotency_key == "livekit:call-1:tool-1"
        assert command.metadata["turn_id"] == "turn-1"
        assert command.metadata["tool_call_id"] == "tool-1"
        assert command.command_id == db.query(ToolCallModel).one().id

        duplicate = asyncio.run(
            execute_livekit_tool(
                request,
                claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )
        assert duplicate == result
        assert len(executor.commands) == 1
        assert db.query(ToolCallModel).count() == 1

        with pytest.raises(HTTPException) as conflict:
            asyncio.run(
                execute_livekit_tool(
                    request.model_copy(update={"arguments": {"changed": True}}),
                    claims(),
                    db,
                    TenantConfigLoader(),
                    CapabilityRouter(),
                    executor,
                )
            )
        assert conflict.value.status_code == 409


def _hotel_claims():
    return claims("penzion_grand", "hotel-call", "hotel-conversation")


def _persist_hotel_turn(db, *, turn_id="hotel-turn"):
    active_call(
        db,
        tenant_id="penzion_grand",
        call_session_id="hotel-call",
        conversation_id="hotel-conversation",
    )
    return persist_livekit_message(
        PersistLiveKitMessageRequest(
            role="user",
            content="Áno, rezerváciu potvrdzujem.",
            turn_id=turn_id,
            item_id=turn_id,
        ),
        _hotel_claims(),
        db,
    )


def _seed_hotel_availability(
    db,
    message_id,
    *,
    check_in="2026-08-29",
    check_out="2026-08-30",
    allocated_room_type="three_bed",
    status="available",
    age=timedelta(),
):
    now = datetime.now() - age
    availability_input = {
        "check_in": check_in,
        "check_out": check_out,
        "room_type": "two_bed",
        "room_count": 1,
    }
    output = {
        "status": status,
        "room_type": "two_bed",
        "requested_room_type": "two_bed",
        "allocated_room_type": (
            allocated_room_type if status == "available" else None
        ),
        "fallback_applied": allocated_room_type != "two_bed",
        "check_in": check_in,
        "check_out": check_out,
        "requested_rooms": 1,
        "available_rooms": 1,
    }
    ToolCallRepository(db).create(
        ToolCall(
            id=f"availability-{check_in}",
            tenant_id="penzion_grand",
            message_id=message_id,
            conversation_id="hotel-conversation",
            call_session_id="hotel-call",
            external_tool_call_id=f"availability-{check_in}",
            request_fingerprint="availability",
            capability_name="reservation.check_availability",
            provider="google_sheets",
            input=availability_input,
            output=output,
            response={"status": "success", "result": output},
            status=ToolCallStatus.SUCCESS,
            latency_ms=1,
            created_at=now,
            updated_at=now,
        )
    )


def _hotel_create_request(*, tool_call_id="create-1", check_in="2026-08-29"):
    return ExecuteLiveKitToolRequest(
        capability="reservation.create_request",
        arguments={
            "check_in": check_in,
            "check_out": "2026-08-30",
            "reservation_name": "Ján Novák",
            "reservation_phone": "+421900111222",
            "room_type": "two_bed",
            "room_count": 1,
            "confirmed": True,
            "caller_number": "+421900111222",
        },
        turn_id="hotel-turn",
        tool_call_id=tool_call_id,
    )


def test_hotel_creation_requires_matching_availability_and_uses_allocation():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    executor = Executor()
    with Session(engine) as db:
        message = _persist_hotel_turn(db)
        _seed_hotel_availability(db, message["message_id"])
        first = asyncio.run(
            execute_livekit_tool(
                _hotel_create_request(),
                _hotel_claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )
        duplicate = asyncio.run(
            execute_livekit_tool(
                _hotel_create_request(tool_call_id="create-2"),
                _hotel_claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )

        assert first.status == "success"
        assert duplicate == first
        assert len(executor.commands) == 1
        assert executor.commands[0].payload["room_type"] == "three_bed"
        assert executor.commands[0].payload["requested_room_type"] == "two_bed"
        assert db.query(ToolCallModel).count() == 2


def test_repeated_identical_availability_call_reuses_fresh_result():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    executor = Executor()
    with Session(engine) as db:
        message = _persist_hotel_turn(db)
        _seed_hotel_availability(db, message["message_id"])
        result = asyncio.run(
            execute_livekit_tool(
                ExecuteLiveKitToolRequest(
                    capability="reservation.check_availability",
                    arguments={
                        "check_in": "2026-08-29",
                        "check_out": "2026-08-30",
                        "room_type": "two_bed",
                        "room_count": 1,
                    },
                    turn_id="hotel-turn",
                    tool_call_id="availability-repeated",
                ),
                _hotel_claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )

        assert result.status == "success"
        assert executor.commands == []
        assert db.query(ToolCallModel).count() == 1


@pytest.mark.parametrize(
    ("seed", "tool_request", "error"),
    [
        (False, _hotel_create_request(), "availability_check_required"),
        (
            True,
            _hotel_create_request(check_in="2026-08-28"),
            "availability_check_required",
        ),
    ],
)
def test_hotel_creation_rejects_missing_or_changed_availability(
    seed, tool_request, error
):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    executor = Executor()
    with Session(engine) as db:
        message = _persist_hotel_turn(db)
        if seed:
            _seed_hotel_availability(db, message["message_id"])
        result = asyncio.run(
            execute_livekit_tool(
                tool_request,
                _hotel_claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )

        assert result.status == "skipped"
        assert result.error == error
        assert executor.commands == []


def test_hotel_creation_rejects_expired_availability():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    executor = Executor()
    with Session(engine) as db:
        message = _persist_hotel_turn(db)
        _seed_hotel_availability(
            db, message["message_id"], age=timedelta(seconds=901)
        )
        result = asyncio.run(
            execute_livekit_tool(
                _hotel_create_request(),
                _hotel_claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )

        assert result.status == "skipped"
        assert result.error == "availability_check_expired"
        assert executor.commands == []


def test_new_availability_request_invalidates_previous_success():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    executor = Executor()
    with Session(engine) as db:
        message = _persist_hotel_turn(db)
        _seed_hotel_availability(
            db, message["message_id"], age=timedelta(seconds=1)
        )
        _seed_hotel_availability(
            db,
            message["message_id"],
            check_in="2026-08-30",
            check_out="2026-08-31",
            status="unavailable",
        )
        result = asyncio.run(
            execute_livekit_tool(
                _hotel_create_request(),
                _hotel_claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )

        assert result.status == "skipped"
        assert result.error == "availability_check_required"
        assert executor.commands == []


def test_unauthorized_tenant_capability_is_rejected():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        active_call(db)
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                execute_livekit_tool(
                    ExecuteLiveKitToolRequest(
                        capability="reservation.check_availability",
                        arguments={},
                        turn_id="turn-1",
                        tool_call_id="tool-1",
                    ),
                    claims(),
                    db,
                    TenantConfigLoader(),
                    CapabilityRouter(),
                    Executor(),
                )
            )
        assert error.value.status_code == 403


def test_duplicate_pending_tool_request_does_not_execute_provider():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    executor = Executor()
    request = ExecuteLiveKitToolRequest(
        capability="reservation.create_request",
        arguments={"reservation_frame": {"guest_name": "Nina"}},
        turn_id="turn-1",
        tool_call_id="tool-pending",
    )
    with Session(engine) as db:
        active_call(db)
        persisted = persist_livekit_message(
            PersistLiveKitMessageRequest(
                role="user", content="Book", turn_id="turn-1", item_id="turn-1"
            ),
            claims(),
            db,
        )
        now = datetime.now()
        ToolCallRepository(db).create(
            ToolCall(
                id="durable-pending",
                tenant_id="demo_restaurant",
                message_id=persisted["message_id"],
                conversation_id="conversation-1",
                call_session_id="call-1",
                external_tool_call_id="tool-pending",
                request_fingerprint=request.request_fingerprint,
                capability_name=request.capability,
                provider="pending",
                input=request.arguments,
                status=ToolCallStatus.PENDING,
                latency_ms=0,
                created_at=now,
                updated_at=now,
            )
        )
        result = asyncio.run(
            execute_livekit_tool(
                request,
                claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )
        assert result.status == "pending"
        assert executor.commands == []


def test_duplicate_failed_tool_request_returns_saved_failure():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    class FailingExecutor(Executor):
        async def execute(self, command):
            self.commands.append(command)
            return CapabilityExecutionResult(
                command_id=command.command_id,
                status=CapabilityExecutionStatus.FAILED,
                error_code="provider_failed",
                error_message="provider failed",
                execution_duration_ms=1,
            )

    executor = FailingExecutor()
    request = ExecuteLiveKitToolRequest(
        capability="reservation.create_request",
        arguments={"reservation_frame": {"guest_name": "Nina"}},
        turn_id="turn-1",
        tool_call_id="tool-failed",
    )
    with Session(engine) as db:
        active_call(db)
        persist_livekit_message(
            PersistLiveKitMessageRequest(
                role="user", content="Book", turn_id="turn-1", item_id="turn-1"
            ),
            claims(),
            db,
        )
        first = asyncio.run(
            execute_livekit_tool(
                request,
                claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )
        duplicate = asyncio.run(
            execute_livekit_tool(
                request,
                claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )
        assert first == duplicate
        assert first.status == "failed"
        assert len(executor.commands) == 1


def test_concurrent_duplicate_tool_requests_execute_provider_once(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tool-idempotency.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        active_call(db)
        persist_livekit_message(
            PersistLiveKitMessageRequest(
                role="user", content="Book", turn_id="turn-1", item_id="turn-1"
            ),
            claims(),
            db,
        )

    class BlockingExecutor(Executor):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def execute(self, command):
            self.commands.append(command)
            self.started.set()
            await self.release.wait()
            return CapabilityExecutionResult(
                command_id=command.command_id,
                status=CapabilityExecutionStatus.SUCCESS,
                result={"accepted": True},
                execution_duration_ms=1,
            )

    executor = BlockingExecutor()
    request = ExecuteLiveKitToolRequest(
        capability="reservation.create_request",
        arguments={"reservation_frame": {"guest_name": "Nina"}},
        turn_id="turn-1",
        tool_call_id="tool-concurrent",
    )

    async def run():
        with sessions() as first_db, sessions() as second_db:
            first = asyncio.create_task(
                execute_livekit_tool(
                    request,
                    claims(),
                    first_db,
                    TenantConfigLoader(),
                    CapabilityRouter(),
                    executor,
                )
            )
            await executor.started.wait()
            duplicate = await execute_livekit_tool(
                request,
                claims(),
                second_db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
            assert duplicate.status == "pending"
            executor.release.set()
            completed = await first
            assert completed.status == "success"

    asyncio.run(run())
    with sessions() as db:
        assert db.query(ToolCallModel).count() == 1
    assert len(executor.commands) == 1


def test_finalize_is_terminal_idempotent_and_rejects_late_writes():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    publisher = Executor()
    with Session(engine) as db:
        active_call(db)
        request = FinalizeLiveKitCallRequest(
            call_session_id="call-1", outcome="completed", reason="participant disconnected"
        )
        first = asyncio.run(finalize_livekit_call(request, claims(), db, publisher))
        second = asyncio.run(finalize_livekit_call(request, claims(), db, publisher))
        assert first.call_status == "completed" and first.queued is True
        assert second.call_status == "completed" and second.queued is False
        assert len(publisher.commands) == 1
        with pytest.raises(HTTPException) as error:
            persist_livekit_message(
                PersistLiveKitMessageRequest(
                    role="user", content="late", turn_id="late", item_id="late"
                ),
                claims(),
                db,
            )
        assert error.value.status_code == 409
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                execute_livekit_tool(
                    ExecuteLiveKitToolRequest(
                        capability="reservation.create_request",
                        arguments={},
                        turn_id="late",
                        tool_call_id="late",
                    ),
                    claims(),
                    db,
                    TenantConfigLoader(),
                    CapabilityRouter(),
                    Executor(),
                )
            )
        assert error.value.status_code == 409


def test_only_livekit_voice_routes_are_exposed():
    paths = {route.path for route in app.routes}
    assert {
        "/api/v1/voice/livekit/sessions",
        "/api/v1/voice/livekit/messages",
        "/api/v1/voice/livekit/tools",
        "/api/v1/voice/livekit/finalize",
    } <= paths
    assert not paths & {
        "/api/messages",
        "/api/v1/messages",
        "/api/conversations",
        "/api/v1/conversations",
        "/api/v1/voice/messages",
        "/api/v1/voice/sessions",
        "/api/v1/voice/stream",
    }


def test_production_has_no_legacy_agent_runtime_dependencies():
    app_root = Path(__file__).parents[1] / "app"
    production = "\n".join(path.read_text() for path in app_root.rglob("*.py"))
    voice_agent = "\n".join(
        path.read_text() for path in (app_root / "voice_agent").rglob("*.py")
    )
    api = "\n".join(path.read_text() for path in (app_root / "api").rglob("*.py"))
    contracts = "\n".join(
        path.read_text() for path in (app_root / "contracts").rglob("*.py")
    )
    assert "langgraph" not in production.lower()
    assert "langchain" not in production.lower()
    assert "app.agent_runtime" not in production
    assert "app.infrastructure" not in voice_agent
    assert "app.integrations" not in voice_agent
    assert "app.capabilities" not in voice_agent
    assert "import redis" not in voice_agent
    assert "app.voice_agent" not in api
    assert "penzion_grand" not in voice_agent
    assert "reservation_request_schema" not in voice_agent
    for forbidden in (
        "app.agent",
        "app.infrastructure",
        "app.integrations",
        "sqlalchemy",
        "livekit.agents",
        "googleapiclient",
    ):
        assert forbidden not in contracts
    assert not (app_root / "voice").joinpath("latency.py").exists()

    compose = (app_root.parent / "docker-compose.yml").read_text()
    voice_service = compose.split("  voice-agent:", 1)[1].split("  redis:", 1)[0]
    assert "GOOGLE_SERVICE_ACCOUNT_FILE" not in voice_service
    assert "google-service-account" not in voice_service
    assert "smoke/tenants" not in voice_service
