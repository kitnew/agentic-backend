import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from contracts import MessageEnvelope
from opentelemetry.trace import Tracer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.application.messaging import EventBus
from backend_core.modules.calls.models import CallSession, CallSessionStatus
from backend_core.platform.database import Database
from backend_core.platform.livekit import EgressResult, LiveKitAdapter
from backend_core.platform.messaging import TransactionalOutboxBus
from backend_core.runtime.finalization.models import CallRecording, RecordingStatus

logger = logging.getLogger(__name__)


def recording_event(recording: CallRecording, status: str) -> MessageEnvelope:
    return MessageEnvelope(
        message_kind="event",
        message_type=f"recording.{status}",
        correlation_id=recording.call_id,
        tenant_id=recording.tenant_id,
        payload={
            "recording_id": str(recording.id),
            "call_id": str(recording.call_id),
            "status": status,
        },
    )


class RecordingService:
    def __init__(self, session: AsyncSession, events: EventBus) -> None:
        self._session = session
        self._events = events

    async def claim(self, call_id: UUID) -> tuple[CallRecording, bool]:
        existing = await self._session.scalar(
            select(CallRecording).where(CallRecording.call_id == call_id)
        )
        if existing is not None:
            return existing, False
        call = await self._session.get(CallSession, call_id)
        if call is None:
            raise ValueError("call not found")
        recording_id = uuid4()
        recording = CallRecording(
            id=recording_id,
            tenant_id=call.tenant_id,
            call_id=call.id,
            provider="livekit_egress",
            status=RecordingStatus.PENDING,
            storage_key=(
                f"recordings/{call.tenant_id}/{call.id}/{recording_id}.mp3"
            ),
            content_type="audio/mpeg",
            start_requested_at=datetime.now(UTC),
        )
        try:
            async with self._session.begin_nested():
                self._session.add(recording)
                await self._session.flush()
        except IntegrityError:
            existing = await self._session.scalar(
                select(CallRecording).where(CallRecording.call_id == call_id)
            )
            if existing is None:
                raise
            return existing, False
        return recording, True

    async def started(self, recording_id: UUID, result: EgressResult) -> None:
        recording = await self._locked(recording_id)
        if recording.status in {RecordingStatus.READY, RecordingStatus.FAILED}:
            return
        if recording.egress_id not in {None, result.egress_id}:
            raise ValueError("recording has a conflicting egress identity")
        recording.egress_id = result.egress_id
        recording.status = RecordingStatus.RECORDING
        recording.started_at = self._timestamp(result.started_at_ns) or datetime.now(UTC)

    async def apply(self, result: EgressResult) -> CallRecording | None:
        recording = await self._session.scalar(
            select(CallRecording)
            .where(CallRecording.egress_id == result.egress_id)
            .with_for_update()
        )
        if recording is None:
            return None
        if recording.status in {RecordingStatus.READY, RecordingStatus.FAILED}:
            return recording
        if result.room_name != (await self._session.get(CallSession, recording.call_id)).room_name:  # type: ignore[union-attr]
            raise ValueError("egress room does not match recording call")
        if result.status in {"starting", "active", "ending"}:
            recording.status = RecordingStatus.RECORDING
            recording.started_at = (
                self._timestamp(result.started_at_ns)
                or recording.started_at
                or datetime.now(UTC)
            )
            return recording
        if result.status == "complete":
            if (
                result.filename != recording.storage_key
                or result.size is None
                or result.size <= 0
                or result.duration_ns is None
                or result.duration_ns < 0
            ):
                await self._failed(recording, "invalid_egress_output", None)
            else:
                recording.status = RecordingStatus.READY
                recording.byte_size = result.size
                recording.duration_ms = result.duration_ns // 1_000_000
                recording.completed_at = (
                    self._timestamp(result.ended_at_ns) or datetime.now(UTC)
                )
                await self._events.publish(recording_event(recording, "ready"))
            return recording
        code = {
            "aborted": "egress_aborted",
            "limit_reached": "egress_limit_reached",
        }.get(result.status, "egress_failed")
        await self._failed(recording, code, result.error)
        return recording

    async def fail_start(self, recording_id: UUID, detail: str) -> None:
        recording = await self._locked(recording_id)
        if recording.status is RecordingStatus.PENDING:
            await self._failed(recording, "egress_start_failed", detail)

    async def _failed(
        self, recording: CallRecording, code: str, detail: str | None
    ) -> None:
        recording.status = RecordingStatus.FAILED
        recording.error_code = code
        recording.error_detail = detail[:1000] if detail else None
        recording.completed_at = datetime.now(UTC)
        await self._events.publish(recording_event(recording, "failed"))

    async def _locked(self, recording_id: UUID) -> CallRecording:
        recording = await self._session.scalar(
            select(CallRecording)
            .where(CallRecording.id == recording_id)
            .with_for_update()
        )
        if recording is None:
            raise ValueError("recording not found")
        return recording

    @staticmethod
    def _timestamp(value: int | None) -> datetime | None:
        return datetime.fromtimestamp(value / 1_000_000_000, UTC) if value else None


class RecordingCoordinator:
    def __init__(
        self,
        database: Database,
        livekit: LiveKitAdapter,
        *,
        event_stream: str,
        command_stream: str,
        tracer: Tracer | None = None,
    ) -> None:
        self._database = database
        self._livekit = livekit
        self._event_stream = event_stream
        self._command_stream = command_stream
        self._tracer = tracer

    def _service(self, session: AsyncSession) -> RecordingService:
        return RecordingService(
            session,
            TransactionalOutboxBus(
                session, self._event_stream, self._command_stream, self._tracer
            ),
        )

    async def ensure(self, call_id: UUID) -> None:
        async with self._database.transaction() as session:
            call = await session.get(CallSession, call_id)
            recording, claimed = await self._service(session).claim(call_id)
            room_name = call.room_name if call is not None else ""
            recording_id = recording.id
            storage_key = recording.storage_key
        if not claimed:
            return
        try:
            result = await self._livekit.start_call_recording(
                room_name=room_name, storage_key=storage_key
            )
            async with self._database.transaction() as session:
                service = self._service(session)
                await service.started(recording_id, result)
                await service.apply(result)
            logger.info(
                "LiveKit call recording started",
                extra={"call_session_id": str(call_id), "egress_id": result.egress_id},
            )
        except Exception as error:
            logger.exception(
                "LiveKit call recording could not start",
                extra={"call_session_id": str(call_id)},
            )
            async with self._database.transaction() as session:
                await self._service(session).fail_start(recording_id, str(error))

    async def apply(self, result: EgressResult) -> CallRecording | None:
        async with self._database.transaction() as session:
            return await self._service(session).apply(result)

    async def reconcile_stale(self, cutoff: datetime, batch_size: int) -> None:
        async with self._database.transaction() as session:
            candidates = list(
                await session.execute(
                    select(
                        CallRecording.id,
                        CallRecording.egress_id,
                        CallRecording.storage_key,
                        CallSession.room_name,
                    )
                    .join(CallSession, CallSession.id == CallRecording.call_id)
                    .where(
                        CallRecording.status.in_(
                            [RecordingStatus.PENDING, RecordingStatus.RECORDING]
                        ),
                        CallRecording.updated_at < cutoff,
                        CallSession.status.in_(
                            [CallSessionStatus.ENDED, CallSessionStatus.FAILED]
                        ),
                    )
                    .limit(batch_size)
                )
            )
        for recording_id, egress_id, storage_key, room_name in candidates:
            try:
                result = (
                    await self._livekit.get_egress(egress_id)
                    if egress_id
                    else await self._livekit.find_egress(
                        room_name=room_name, storage_key=storage_key
                    )
                )
                if result is None:
                    if egress_id is None:
                        async with self._database.transaction() as session:
                            await self._service(session).fail_start(
                                recording_id, "stale start intent has no LiveKit egress"
                            )
                    continue
                async with self._database.transaction() as session:
                    service = self._service(session)
                    if egress_id is None:
                        await service.started(recording_id, result)
                    await service.apply(result)
            except Exception:  # recording recovery must not affect call reconciliation
                logger.exception(
                    "Could not reconcile stale LiveKit recording",
                    extra={"recording_id": str(recording_id)},
                )
