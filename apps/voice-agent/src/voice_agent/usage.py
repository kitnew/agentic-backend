"""Coalesced, best-effort delivery of LiveKit session usage snapshots."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from contracts import CallModelUsage, CallUsageReport
from livekit import agents

from voice_agent.backend import BackendClient
from voice_agent.observability import VoiceMetrics

logger = logging.getLogger(__name__)


class CallUsageReporter:
    def __init__(
        self,
        backend: BackendClient,
        call_id: UUID,
        session: agents.AgentSession,
        provider_hints: dict[str, str],
        metrics: VoiceMetrics | None,
        model_hints: dict[str, str] | None = None,
    ) -> None:
        self._backend = backend
        self._call_id = call_id
        self._session = session
        self._provider_hints = provider_hints
        self._model_hints = model_hints or {}
        self._metrics = metrics
        self._dirty = False
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        session.on("session_usage_updated", self._on_usage)

    def _on_usage(self, _: object) -> None:
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._debounced_flush())

    async def _debounced_flush(self) -> None:
        try:
            while self._dirty:
                await asyncio.sleep(5)
                await self._send()
        except asyncio.CancelledError:
            pass

    def snapshot(self) -> CallUsageReport:
        observed_at = datetime.now(UTC)
        rows = []
        for usage in self._session.usage.model_usage:
            service = usage.type.removesuffix("_usage")
            if service not in {"llm", "stt", "tts"}:
                continue
            values = usage.model_dump(exclude={"type", "provider", "model"})
            rows.append(
                CallModelUsage(
                    provider=self._provider_hints.get(service, usage.provider)
                    if usage.provider in {"", "openai", "azure"}
                    else usage.provider,
                    service=cast(Literal["llm", "stt", "tts"], service),
                    model=usage.model or self._model_hints.get(service, "unknown"),
                    observed_at=observed_at,
                    counters=values,
                )
            )
        return CallUsageReport(usage=rows)

    async def _send(self) -> None:
        async with self._lock:
            self._dirty = False
            try:
                report = self.snapshot()
                if report.usage:
                    await self._backend.report_ai_usage(self._call_id, report)
            except Exception:
                logger.exception(
                    "Call AI usage persistence failed",
                    extra={"call_id": str(self._call_id)},
                )
                if self._metrics is not None:
                    self._metrics.record_usage_persistence_failure()

    async def flush(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self._send()
