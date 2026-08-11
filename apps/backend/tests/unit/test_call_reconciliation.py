from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from backend_core.modules.calls.models import CallSessionStatus
from backend_core.modules.calls.reconciliation import CallRuntimeReconciler
from backend_core.modules.calls.repository import StaleRuntimeCall


class Database:
    @asynccontextmanager
    async def transaction(self):
        yield object()


class LiveKit:
    def __init__(self, rooms: dict[str, bool]) -> None:
        self.rooms = rooms

    async def room_exists(self, room_name: str) -> bool:
        return self.rooms[room_name]


@pytest.mark.asyncio
async def test_reconciler_only_transitions_calls_with_a_missing_livekit_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = StaleRuntimeCall(uuid4(), CallSessionStatus.CONNECTED, "gone")
    active = StaleRuntimeCall(uuid4(), CallSessionStatus.CONNECTED, "active")
    reconciled: list[object] = []

    class Repository:
        def __init__(self, session: object) -> None:
            pass

        async def list_stale_runtime_calls(self, cutoff, limit):
            return [stale, active]

    class Service:
        async def reconcile_missing_runtime(self, call_id):
            reconciled.append(call_id)

    monkeypatch.setattr(
        "backend_core.modules.calls.reconciliation.CallSessionRepository", Repository
    )
    monkeypatch.setattr(
        "backend_core.modules.calls.reconciliation.build_call_session_service",
        lambda *args: Service(),
    )

    await CallRuntimeReconciler(
        Database(),  # type: ignore[arg-type]
        LiveKit({"gone": False, "active": True}),  # type: ignore[arg-type]
        grace_seconds=60,
        batch_size=10,
        event_stream="domain:events",
        command_stream="application:commands",
    ).run_once()

    assert reconciled == [stale.id]


@pytest.mark.asyncio
async def test_reconciler_does_not_transition_without_a_stale_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    class Repository:
        def __init__(self, session: object) -> None:
            pass

        async def list_stale_runtime_calls(self, cutoff: datetime, limit: int):
            assert cutoff < datetime.now(UTC)
            return []

    monkeypatch.setattr(
        "backend_core.modules.calls.reconciliation.CallSessionRepository", Repository
    )

    class LiveKitNeverCalled:
        async def room_exists(self, room_name: str) -> bool:
            nonlocal called
            called = True
            return False

    await CallRuntimeReconciler(
        Database(),  # type: ignore[arg-type]
        LiveKitNeverCalled(),  # type: ignore[arg-type]
        grace_seconds=60,
        batch_size=10,
        event_stream="domain:events",
        command_stream="application:commands",
    ).run_once()

    assert not called
