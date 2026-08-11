import asyncio
import logging
from datetime import UTC, datetime, timedelta

from backend_core.modules.calls.repository import CallSessionRepository
from backend_core.modules.calls.router import build_call_session_service
from backend_core.platform.database import Database
from backend_core.platform.livekit import LiveKitAdapter

logger = logging.getLogger(__name__)


class CallRuntimeReconciler:
    def __init__(
        self,
        database: Database,
        livekit: LiveKitAdapter,
        *,
        grace_seconds: float,
        batch_size: int,
        event_stream: str,
        command_stream: str,
    ) -> None:
        self._database = database
        self._livekit = livekit
        self._grace = timedelta(seconds=grace_seconds)
        self._batch_size = batch_size
        self._event_stream = event_stream
        self._command_stream = command_stream

    async def run_once(self) -> None:
        cutoff = datetime.now(UTC) - self._grace
        async with self._database.transaction() as session:
            candidates = await CallSessionRepository(session).list_stale_runtime_calls(
                cutoff, self._batch_size
            )
        for candidate in candidates:
            try:
                if await self._livekit.room_exists(candidate.room_name):
                    continue
            except Exception:  # noqa: BLE001 - unavailable runtime evidence must not end calls
                logger.warning(
                    "Call runtime reconciliation could not inspect LiveKit room",
                    extra={"call_session_id": str(candidate.id)},
                )
                continue
            async with self._database.transaction() as session:
                call = await build_call_session_service(
                    session, self._event_stream, self._command_stream
                ).reconcile_missing_runtime(candidate.id)
                if call is not None:
                    logger.info(
                        "Reconciled call with missing LiveKit runtime",
                        extra={"call_session_id": str(call.id), "status": call.status},
                    )

    async def run(self, interval_seconds: float) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(interval_seconds)
