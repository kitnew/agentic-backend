import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from backend_core.modules.calls.errors import HumanHandoffError
from backend_core.modules.calls.models import (
    CallChannel,
    CallDirection,
    CallSession,
    CallSessionStatus,
)
from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.calls.service import CallSessionService
from backend_core.modules.tenants.models import Tenant, TenantStatus
from backend_core.modules.tenants.repository import TenantRepository
from contracts import HandoffEvent, HandoffState, HumanHandoffRequest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)


class LiveKit:
    def __init__(self) -> None:
        self.removed: list[tuple[str, str]] = []
        self.created: list[str] = []

    async def remove_participant(self, room_name: str, identity: str) -> None:
        self.removed.append((room_name, identity))

    async def create_sip_participant(self, **kwargs):
        self.created.append(kwargs["participant_identity"])
        return kwargs["participant_identity"], f"sip-{len(self.created)}"


@pytest_asyncio.fixture
async def database_engine(migrated_database_url: str):
    engine = create_async_engine(migrated_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


async def seed_call(
    engine: AsyncEngine,
    handoff_state: HandoffState | None,
) -> tuple[UUID, UUID | None]:
    tenant_id = uuid4()
    call_id = uuid4()
    attempt_id = uuid4() if handoff_state is not None else None
    now = datetime.now(UTC)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker.begin() as session:
        session.add(
            Tenant(
                id=tenant_id,
                slug=f"tenant-{tenant_id.hex}",
                display_name="Concurrency tenant",
                business_type="hotel",
                status=TenantStatus.ACTIVE,
            )
        )
        await session.flush()
        session.add(
            CallSession(
                id=call_id,
                tenant_id=tenant_id,
                execution_id=uuid4(),
                backend_execution_context={},
                channel=CallChannel.SIP,
                direction=CallDirection.INBOUND,
                provider="livekit",
                provider_call_id=f"provider-{call_id}",
                livekit_participant_identity="caller",
                room_name=f"room-{call_id}",
                status=CallSessionStatus.CONNECTED,
                started_at=now,
                connected_at=now,
                handoff_tool_call_id="existing-tool" if attempt_id else None,
                handoff_attempt_id=attempt_id,
                handoff_state=handoff_state,
                handoff_destination="reception" if attempt_id else None,
                handoff_participant_identity=(
                    f"handoff-{attempt_id}" if attempt_id else None
                ),
            )
        )
    return call_id, attempt_id


def transition_service(session) -> CallSessionService:
    return CallSessionService(
        CallSessionRepository(session),
        None,
        None,
        None,
        None,
        None,  # type: ignore[arg-type]
    )


async def ordered_transition_race(
    engine: AsyncEngine,
    call_id: UUID,
    attempt_id: UUID,
    winner: HandoffEvent,
    loser: HandoffEvent,
    livekit: LiveKit,
) -> tuple[HandoffState, HandoffState, HandoffState]:
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def run_loser():
        async with maker.begin() as session:
            return await transition_service(session).transition_handoff(
                call_id,
                attempt_id,
                loser,
                livekit,  # type: ignore[arg-type]
            )

    async with maker() as winner_session:
        await winner_session.begin()
        winner_repository = CallSessionRepository(winner_session)
        assert await winner_repository.get_for_update(call_id) is not None
        loser_task = asyncio.create_task(run_loser())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(loser_task), 0.05)
        winner_result = await transition_service(winner_session).transition_handoff(
            call_id,
            attempt_id,
            winner,
            livekit,  # type: ignore[arg-type]
        )
        await winner_session.commit()
    loser_result = await loser_task

    async with maker() as verification_session:
        persisted = await verification_session.get(CallSession, call_id)
        assert persisted is not None
        final_state = persisted.handoff_state
    assert final_state is not None
    return winner_result.state, loser_result.state, final_state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("winner", "loser", "expected"),
    [
        (HandoffEvent.CANCEL, HandoffEvent.COMPLETE, HandoffState.CANCELED),
        (HandoffEvent.COMPLETE, HandoffEvent.CANCEL, HandoffState.COMPLETED),
        (HandoffEvent.TIME_OUT, HandoffEvent.COMPLETE, HandoffState.TIMED_OUT),
        (HandoffEvent.FAIL, HandoffEvent.COMPLETE, HandoffState.FAILED),
    ],
)
async def test_postgresql_serializes_terminal_handoff_races(
    database_engine: AsyncEngine,
    winner: HandoffEvent,
    loser: HandoffEvent,
    expected: HandoffState,
) -> None:
    call_id, attempt_id = await seed_call(database_engine, HandoffState.ANSWERED)
    assert attempt_id is not None
    livekit = LiveKit()

    first, second, persisted = await ordered_transition_race(
        database_engine, call_id, attempt_id, winner, loser, livekit
    )

    assert first is second is persisted is expected
    assert livekit.removed == (
        [(f"room-{call_id}", f"handoff-{attempt_id}")]
        if expected in {HandoffState.CANCELED, HandoffState.TIMED_OUT}
        else []
    )


@pytest.mark.asyncio
async def test_postgresql_serializes_duplicate_cancellation(
    database_engine: AsyncEngine,
) -> None:
    call_id, attempt_id = await seed_call(database_engine, HandoffState.DIALING)
    assert attempt_id is not None
    livekit = LiveKit()

    first, second, persisted = await ordered_transition_race(
        database_engine,
        call_id,
        attempt_id,
        HandoffEvent.CANCEL,
        HandoffEvent.CANCEL,
        livekit,
    )

    assert first is second is persisted is HandoffState.CANCELED
    assert livekit.removed == [
        (f"room-{call_id}", f"handoff-{attempt_id}"),
        (f"room-{call_id}", f"handoff-{attempt_id}"),
    ]


@pytest.mark.asyncio
async def test_postgresql_rejects_old_attempt_cancellation(
    database_engine: AsyncEngine,
) -> None:
    call_id, current_attempt_id = await seed_call(database_engine, HandoffState.DIALING)
    assert current_attempt_id is not None
    maker = async_sessionmaker(database_engine, expire_on_commit=False)

    with pytest.raises(HumanHandoffError, match="handoff_attempt_mismatch"):
        async with maker.begin() as session:
            await transition_service(session).transition_handoff(
                call_id,
                uuid4(),
                HandoffEvent.CANCEL,
                LiveKit(),  # type: ignore[arg-type]
            )

    async with maker() as verification_session:
        persisted = await verification_session.get(CallSession, call_id)
        assert persisted is not None
        assert persisted.handoff_attempt_id == current_attempt_id
        assert persisted.handoff_state is HandoffState.DIALING


@pytest.mark.asyncio
async def test_postgresql_allows_only_one_concurrent_handoff_start(
    database_engine: AsyncEngine,
) -> None:
    call_id, _ = await seed_call(database_engine, None)
    maker = async_sessionmaker(database_engine, expire_on_commit=False)
    livekit = LiveKit()

    def service(session) -> CallSessionService:
        instance = CallSessionService(
            CallSessionRepository(session),
            SimpleNamespace(
                platform=lambda: None,
            ),
            TenantRepository(session),
            None,
            None,
            None,  # type: ignore[arg-type]
        )

        async def pinned_handoff(_call, _destination):
            return "+421551234567", SimpleNamespace(phone_number="+421900000001")

        instance._pinned_handoff = pinned_handoff  # type: ignore[method-assign]

        class Routes:
            async def platform(self):
                return SimpleNamespace(
                    outbound_trunk_id="ST_outbound",
                    provisioning_status=SimpleNamespace(value="ready"),
                )

        instance._routes = Routes()  # type: ignore[assignment]
        return instance

    async def run_second_start():
        try:
            async with maker.begin() as session:
                return await service(session).transfer_to_human(
                    call_id,
                    HumanHandoffRequest(
                        tool_call_id="second-tool", destination="reception"
                    ),
                    livekit,  # type: ignore[arg-type]
                )
        except HumanHandoffError as error:
            return error

    async with maker() as winner_session:
        await winner_session.begin()
        assert (
            await CallSessionRepository(winner_session).get_for_update(call_id)
            is not None
        )
        second_task = asyncio.create_task(run_second_start())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(second_task), 0.05)
        winner = await service(winner_session).transfer_to_human(
            call_id,
            HumanHandoffRequest(tool_call_id="first-tool", destination="reception"),
            livekit,  # type: ignore[arg-type]
        )
        await winner_session.commit()
    loser = await second_task

    async with maker() as verification_session:
        persisted = await verification_session.get(CallSession, call_id)
        assert persisted is not None
        assert persisted.handoff_attempt_id == winner.attempt_id
        assert persisted.handoff_state is HandoffState.DIALING
    assert isinstance(loser, HumanHandoffError)
    assert str(loser) == "call_not_transferable"
    assert len(livekit.created) == 1
