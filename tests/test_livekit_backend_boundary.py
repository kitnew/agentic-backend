import asyncio
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.voice_sessions import (
    ExecuteLiveKitToolRequest,
    PersistLiveKitMessageRequest,
    execute_livekit_tool,
    persist_livekit_message,
)
from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityExecutionResult, CapabilityExecutionStatus
from app.infrastructure.database import Base
from app.infrastructure.models import MessageModel
from app.tenants.loader import TenantConfigLoader
from app.voice.session_token import VoiceSessionClaims


def claims():
    now = int(time.time())
    return VoiceSessionClaims(
        tenant_id="demo_restaurant",
        call_session_id="call-1",
        conversation_id="conversation-1",
        language="sk",
        timezone="Europe/Bratislava",
        iat=now,
        exp=now + 60,
        mode="call",
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


def test_voice_messages_are_idempotent_and_preserve_interruption_state():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
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
        result = asyncio.run(
            execute_livekit_tool(
                ExecuteLiveKitToolRequest(
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
                ),
                claims(),
                db,
                TenantConfigLoader(),
                CapabilityRouter(),
                executor,
            )
        )
        command = executor.commands[0]
        assert result["status"] == "success"
        assert command.tenant_id == "demo_restaurant"
        assert command.conversation_id == "conversation-1"
        assert command.call_session_id == "call-1"
        assert command.idempotency_key == "livekit:call-1:tool-1"
        assert command.metadata["turn_id"] == "turn-1"
        assert command.metadata["tool_call_id"] == "tool-1"


def test_unauthorized_tenant_capability_is_rejected():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
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


def test_production_has_no_langgraph_or_voice_agent_infrastructure_imports():
    app_root = Path(__file__).parents[1] / "app"
    production = "\n".join(path.read_text() for path in app_root.rglob("*.py"))
    voice_agent = "\n".join(
        path.read_text() for path in (app_root / "voice_agent").rglob("*.py")
    )
    assert "langgraph" not in production.lower()
    assert "app.infrastructure" not in voice_agent
    assert "import redis" not in voice_agent
