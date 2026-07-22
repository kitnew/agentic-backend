import asyncio
import hashlib
import json
import logging
import math
import os
import signal
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import perf_counter
from uuid import uuid4

from app.application.capabilities.boundary import InProcessCapabilityExecutor
from app.capabilities.schemas import (
    CapabilityCommand,
    CapabilityExecutionResult,
    CapabilityExecutionStatus,
)
from app.core.config import CapabilitySettings
from app.contracts.livekit import ExecuteLiveKitToolResponse
from app.domain.tool_calls.enums import ToolCallStatus
from app.application.call_finalization import finalize_call
from app.infrastructure.database import SessionLocal
from app.infrastructure.repositories.tool_call_repository import ToolCallRepository


logger = logging.getLogger(__name__)


class WorkerCommandExecutor:
    def __init__(self, capabilities=None):
        self.capabilities = capabilities or InProcessCapabilityExecutor()

    async def execute(self, command: CapabilityCommand) -> CapabilityExecutionResult:
        if command.capability != "call" or command.action != "finalize":
            result = await self.capabilities.execute(command)
            if result.status == CapabilityExecutionStatus.SUCCESS:
                _persist_tool_result(command, result)
            return result
        if not command.call_session_id:
            raise ValueError("call_session_id is required for call finalization")
        with SessionLocal() as db:
            result = await finalize_call(db, command.call_session_id)
        return CapabilityExecutionResult(
            command_id=command.command_id,
            status=CapabilityExecutionStatus.SUCCESS,
            result=result,
            execution_duration_ms=0,
            metadata=command.metadata,
        )


def _persist_tool_result(
    command: CapabilityCommand, result: CapabilityExecutionResult
) -> None:
    tool_call_id = command.metadata.get("durable_tool_call_id")
    if not tool_call_id:
        return
    status = "failed"
    if result.status == CapabilityExecutionStatus.SUCCESS:
        status = result.metadata.get("legacy_status") or "success"
    if status not in {item.value for item in ToolCallStatus if item != ToolCallStatus.PENDING}:
        status = "failed"
    response = ExecuteLiveKitToolResponse(
        status=status,
        message=result.metadata.get("user_message"),
        error=result.error_message,
        result=result.result,
        tool_call_id=tool_call_id,
    )
    with SessionLocal() as db:
        repository = ToolCallRepository(db)
        if repository.get_by_id(tool_call_id) is None:
            return
        repository.complete_livekit(
            tool_call_id,
            status=ToolCallStatus(status),
            provider=result.metadata.get("provider") or "capability_worker",
            output=result.result,
            error=result.error_message,
            response=response.model_dump(mode="json"),
            latency_ms=result.execution_duration_ms,
            updated_at=datetime.now(),
        )


class CapabilityWorker:
    def __init__(
        self,
        redis_client,
        *,
        settings: CapabilitySettings | None = None,
        executor=None,
        consumer_name: str | None = None,
        sleep=asyncio.sleep,
    ):
        self.redis = redis_client
        self.settings = settings or CapabilitySettings.from_env()
        self.settings.validate()
        self.executor = executor or WorkerCommandExecutor()
        self.consumer_name = consumer_name or f"{socket.gethostname()}-{os.getpid()}"
        self.sleep = sleep
        self.stopping = asyncio.Event()
        self.tasks: set[asyncio.Task] = set()
        self.active_ids: set[str] = set()
        self.claim_cursor = "0-0"

    def stop(self) -> None:
        self.stopping.set()

    async def create_group(self) -> None:
        from redis.exceptions import ResponseError

        try:
            await self.redis.xgroup_create(
                self.settings.command_stream,
                self.settings.consumer_group,
                id="0-0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def run(self) -> None:
        await self.create_group()
        while not self.stopping.is_set():
            capacity = self.settings.worker_concurrency - len(self.tasks)
            if capacity <= 0:
                await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
                continue

            entries = await self.recover_pending(capacity)
            if not entries and not self.stopping.is_set():
                entries = await self.read_new(capacity)
            for stream_id, fields in entries:
                if self.stopping.is_set():
                    break
                self._start(stream_id, fields)

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

    async def recover_pending(self, count: int | None = None) -> list[tuple[str, dict]]:
        count = count or self.settings.worker_concurrency
        response = await self.redis.xautoclaim(
            self.settings.command_stream,
            self.settings.consumer_group,
            self.consumer_name,
            min_idle_time=max(1, math.ceil(self.settings.pending_idle_seconds * 1000)),
            start_id=self.claim_cursor,
            count=count,
        )
        self.claim_cursor = _text(response[0])
        entries = [
            (_text(stream_id), fields)
            for stream_id, fields in response[1]
            if _text(stream_id) not in self.active_ids
        ]
        for stream_id, fields in entries:
            context = {}
            try:
                command_data = _field(fields, "command")
                if command_data is not None:
                    context = _context(CapabilityCommand.model_validate_json(command_data))
            except Exception:
                pass
            logger.info(
                "Capability command recovered",
                extra={**context, "event": "recovery", "stream_id": stream_id},
            )
        return entries

    async def read_new(self, count: int | None = None) -> list[tuple[str, dict]]:
        response = await self.redis.xreadgroup(
            self.settings.consumer_group,
            self.consumer_name,
            {self.settings.command_stream: ">"},
            count=count or self.settings.worker_concurrency,
            block=1000,
        )
        return [
            (_text(stream_id), fields)
            for _, entries in response
            for stream_id, fields in entries
        ]

    def _start(self, stream_id: str, fields: dict) -> None:
        self.active_ids.add(stream_id)
        task = asyncio.create_task(self._guard_entry(stream_id, fields))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _guard_entry(self, stream_id: str, fields: dict) -> None:
        try:
            await self.process_entry(stream_id, fields)
        except Exception:
            logger.exception(
                "Capability command processing failed; entry remains pending",
                extra={"event": "failure", "stream_id": stream_id},
            )
        finally:
            self.active_ids.discard(stream_id)

    async def process_entry(self, stream_id: str, fields: dict) -> None:
        raw = _field(fields, "command")
        raw_text = _text(raw) if raw is not None else ""
        while True:
            try:
                command = CapabilityCommand.model_validate_json(raw_text)
            except Exception as exc:
                attempt = await self.redis.incr(self.settings.attempt_key(stream_id))
                if attempt <= self.settings.max_retries:
                    await self._retry(stream_id, attempt, str(exc))
                    continue
                command_id, metadata = _correlation(raw_text)
                result = (
                    CapabilityExecutionResult(
                        command_id=command_id,
                        status=CapabilityExecutionStatus.FAILED,
                        error_code="serialization_error",
                        error_message=str(exc),
                        execution_duration_ms=0,
                        metadata=metadata,
                    )
                    if command_id
                    else None
                )
                await self._store_terminal(
                    stream_id,
                    raw_text,
                    result,
                    attempt,
                    error=str(exc),
                    dead_letter=True,
                )
                return

            cached = await self._cached(self.settings.completion_key(command.command_id))
            if cached:
                await self._store_terminal(
                    stream_id,
                    raw_text,
                    cached.model_copy(
                        update={"metadata": {**cached.metadata, **command.metadata}}
                    ),
                    0,
                    command=command,
                )
                return

            completion_lock = self.settings.completion_lock_key(command.command_id)
            if not await self._lock(completion_lock):
                await self.sleep(0.05)
                continue
            locks = [completion_lock]

            digest = _idempotency_digest(command)
            if digest:
                cached = await self._cached(self.settings.idempotency_key(digest))
                if cached:
                    await self._store_terminal(
                        stream_id,
                        raw_text,
                        self._reuse(cached, command),
                        0,
                        command=command,
                        locks=locks,
                    )
                    return
                idempotency_lock = self.settings.idempotency_lock_key(digest)
                if not await self._lock(idempotency_lock):
                    await self._release(locks)
                    await self.sleep(0.05)
                    continue
                locks.append(idempotency_lock)

            attempt = await self.redis.incr(self.settings.attempt_key(stream_id))
            logger.info(
                "Capability command attempt started",
                extra={
                    **_context(command),
                    "event": "attempt",
                    "stream_id": stream_id,
                    "attempt": attempt,
                },
            )
            result = await self._execute(command)
            if result.status == CapabilityExecutionStatus.SUCCESS:
                await self._store_terminal(
                    stream_id,
                    raw_text,
                    result,
                    attempt,
                    command=command,
                    locks=locks,
                )
                return

            if attempt <= self.settings.max_retries:
                await self._release(locks)
                await self._retry(
                    stream_id,
                    attempt,
                    result.error_message or result.error_code or "execution failed",
                    command,
                )
                continue

            await self._store_terminal(
                stream_id,
                raw_text,
                result,
                attempt,
                command=command,
                error=result.error_message or result.error_code or "execution failed",
                dead_letter=True,
                locks=locks,
            )
            return

    async def _execute(self, command: CapabilityCommand) -> CapabilityExecutionResult:
        started_at = perf_counter()
        try:
            with ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="capability-worker",
            ) as thread:
                future = thread.submit(asyncio.run, self.executor.execute(command))
                while not future.done():
                    await asyncio.sleep(0.01)
                result = future.result()
            result = CapabilityExecutionResult.model_validate(result)
            if result.command_id != command.command_id:
                raise ValueError("executor returned a mismatched command_id")
            return result
        except Exception as exc:
            return CapabilityExecutionResult(
                command_id=command.command_id,
                status=CapabilityExecutionStatus.FAILED,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
                execution_duration_ms=int((perf_counter() - started_at) * 1000),
                metadata=command.metadata,
            )

    async def _retry(
        self,
        stream_id: str,
        attempt: int,
        error: str,
        command: CapabilityCommand | None = None,
    ) -> None:
        delay = min(4, 2 ** (attempt - 1))
        logger.warning(
            "Capability command will retry",
            extra={
                **(_context(command) if command else {}),
                "event": "failure",
                "stream_id": stream_id,
                "attempt": attempt,
                "retry_delay_seconds": delay,
                "error": error,
            },
        )
        await self.sleep(delay)

    async def _store_terminal(
        self,
        stream_id: str,
        raw: str,
        result: CapabilityExecutionResult | None,
        attempt: int,
        *,
        command: CapabilityCommand | None = None,
        error: str | None = None,
        dead_letter: bool = False,
        locks: list[str] | None = None,
    ) -> None:
        if (
            dead_letter
            and command
            and result
            and result.status == CapabilityExecutionStatus.FAILED
        ):
            _persist_tool_result(command, result)
        pipe = self.redis.pipeline(transaction=True)
        if result:
            serialized = result.model_dump_json()
            pipe.rpush(self.settings.result_key(result.command_id), serialized)
            pipe.expire(
                self.settings.result_key(result.command_id),
                self.settings.result_ttl_seconds,
            )
            pipe.set(
                self.settings.completion_key(result.command_id),
                serialized,
                ex=self.settings.result_ttl_seconds,
            )
            digest = _idempotency_digest(command) if command else None
            if result.status == CapabilityExecutionStatus.SUCCESS and digest:
                pipe.set(
                    self.settings.idempotency_key(digest),
                    serialized,
                    ex=self.settings.idempotency_ttl_seconds,
                )
        if dead_letter:
            pipe.xadd(
                self.settings.dead_letter_stream,
                {
                    "stream_id": stream_id,
                    "command": raw,
                    "command_id": result.command_id if result else "",
                    "error": error or "unknown error",
                    "attempts": str(attempt),
                },
            )
        pipe.xack(
            self.settings.command_stream,
            self.settings.consumer_group,
            stream_id,
        )
        pipe.xdel(self.settings.command_stream, stream_id)
        pipe.delete(self.settings.attempt_key(stream_id))
        if locks:
            pipe.delete(*locks)
        await pipe.execute()
        logger.info(
            "Capability command completed",
            extra={
                **(_context(command) if command else {}),
                "event": "dead_letter" if dead_letter else "status",
                "stream_id": stream_id,
                "attempt": attempt,
                "status": result.status.value if result else "uncorrelated",
                "duration": result.execution_duration_ms if result else 0,
            },
        )

    async def _cached(self, key: str) -> CapabilityExecutionResult | None:
        serialized = await self.redis.get(key)
        if not serialized:
            return None
        try:
            return CapabilityExecutionResult.model_validate_json(serialized)
        except Exception:
            await self.redis.delete(key)
            return None

    async def _lock(self, key: str) -> bool:
        ttl = max(
            1,
            math.ceil(self.settings.pending_idle_seconds * 2),
            math.ceil(self.settings.result_timeout_seconds * 2),
        )
        return bool(await self.redis.set(key, uuid4().hex, nx=True, ex=ttl))

    async def _release(self, keys: list[str]) -> None:
        if keys:
            await self.redis.delete(*keys)

    def _reuse(
        self,
        cached: CapabilityExecutionResult,
        command: CapabilityCommand,
    ) -> CapabilityExecutionResult:
        metadata = {
            **cached.metadata,
            **command.metadata,
            "idempotency_reused": True,
        }
        if command.call_session_id:
            metadata["call_session_id"] = command.call_session_id
        return cached.model_copy(
            update={"command_id": command.command_id, "metadata": metadata}
        )


def _idempotency_digest(command: CapabilityCommand | None) -> str | None:
    if not command or not command.idempotency_key:
        return None
    value = f"{command.tenant_id}\0{command.idempotency_key}".encode()
    return hashlib.sha256(value).hexdigest()


def _correlation(raw: str) -> tuple[str | None, dict]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None, {}
    if not isinstance(value, dict):
        return None, {}
    command_id = value.get("command_id")
    metadata = value.get("metadata")
    return (
        command_id if isinstance(command_id, str) and command_id else None,
        metadata if isinstance(metadata, dict) else {},
    )


def _field(fields: dict, name: str):
    return fields.get(name, fields.get(name.encode()))


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _context(command: CapabilityCommand) -> dict:
    return {
        "command_id": command.command_id,
        "tenant_id": command.tenant_id,
        "conversation_id": command.conversation_id,
        "call_session_id": command.call_session_id,
        "capability": command.capability,
        "action": command.action,
    }


async def run_worker() -> None:
    from redis.asyncio import Redis

    settings = CapabilitySettings.from_env()
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    worker = CapabilityWorker(redis_client, settings=settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stop)
    try:
        await worker.run()
    finally:
        await redis_client.aclose()


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
