import asyncio
import logging
from contextlib import suppress
from time import monotonic, perf_counter

from app.capabilities.schemas import (
    CapabilityCommand,
    CapabilityExecutionResult,
    CapabilityExecutionStatus,
)
from app.core.config import CapabilitySettings


logger = logging.getLogger(__name__)


class RedisCapabilityExecutor:
    def __init__(
        self,
        *,
        settings: CapabilitySettings | None = None,
        redis_client=None,
    ):
        self.settings = settings or CapabilitySettings.from_env()
        self.settings.validate()
        self.redis_client = redis_client

    async def execute(self, command: CapabilityCommand) -> CapabilityExecutionResult:
        started_at = perf_counter()
        try:
            serialized = command.model_dump_json()
        except Exception as exc:
            return self._failure(command, "serialization_error", str(exc), started_at)

        client = self.redis_client or self._new_client()
        try:
            stream_id = await client.xadd(
                self.settings.command_stream,
                {"command": serialized},
            )
            logger.info(
                "Capability command published",
                extra={
                    **self._context(command),
                    "event": "publication",
                    "stream_id": _text(stream_id),
                    "duration": int((perf_counter() - started_at) * 1000),
                },
            )
            result = await self._wait_for_result(client, command, started_at)
        except asyncio.TimeoutError:
            result = self._failure(
                command,
                "capability_result_timeout",
                f"Capability result timed out after {self.settings.result_timeout_seconds:g} seconds",
                started_at,
            )
        except Exception as exc:
            result = self._failure(command, "redis_error", str(exc), started_at)
        finally:
            if self.redis_client is None:
                with suppress(Exception):
                    await client.aclose()

        logger.info(
            "Capability command finished",
            extra={
                **self._context(command),
                "event": "status",
                "status": result.status.value,
                "duration": result.execution_duration_ms,
            },
        )
        return result

    async def enqueue(self, command: CapabilityCommand) -> str:
        serialized = command.model_dump_json()
        client = self.redis_client or self._new_client()
        try:
            return _text(
                await client.xadd(self.settings.command_stream, {"command": serialized})
            )
        finally:
            if self.redis_client is None:
                with suppress(Exception):
                    await client.aclose()

    async def _wait_for_result(
        self,
        client,
        command: CapabilityCommand,
        started_at: float,
    ) -> CapabilityExecutionResult:
        deadline = monotonic() + self.settings.result_timeout_seconds
        key = self.settings.result_key(command.command_id)
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            try:
                item = await asyncio.wait_for(
                    client.blpop(key, timeout=remaining),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                break
            if item is None:
                await asyncio.sleep(min(0.01, max(0, deadline - monotonic())))
                continue
            try:
                result = CapabilityExecutionResult.model_validate_json(item[1])
            except Exception:
                logger.warning(
                    "Malformed capability result ignored",
                    extra={**self._context(command), "event": "receipt"},
                )
                continue
            if result.command_id != command.command_id:
                logger.warning(
                    "Mismatched capability result ignored",
                    extra={
                        **self._context(command),
                        "event": "receipt",
                        "received_command_id": result.command_id,
                    },
                )
                continue
            logger.info(
                "Capability result received",
                extra={
                    **self._context(command),
                    "event": "receipt",
                    "status": result.status.value,
                    "duration": result.execution_duration_ms,
                },
            )
            return result
        logger.warning(
            "Capability result timed out",
            extra={
                **self._context(command),
                "event": "timeout",
                "duration": int((perf_counter() - started_at) * 1000),
            },
        )
        return self._failure(
            command,
            "capability_result_timeout",
            f"Capability result timed out after {self.settings.result_timeout_seconds:g} seconds",
            started_at,
        )

    def _new_client(self):
        from redis.asyncio import Redis

        return Redis.from_url(
            self.settings.redis_url,
            decode_responses=True,
            socket_timeout=None,
        )

    def _failure(
        self,
        command: CapabilityCommand,
        error_code: str,
        error_message: str,
        started_at: float,
    ) -> CapabilityExecutionResult:
        result = CapabilityExecutionResult(
            command_id=command.command_id,
            status=CapabilityExecutionStatus.FAILED,
            error_code=error_code,
            error_message=error_message,
            execution_duration_ms=int((perf_counter() - started_at) * 1000),
            metadata=command.metadata,
        )
        logger.error(
            "Capability command failed",
            extra={
                **self._context(command),
                "event": "failure",
                "status": result.status.value,
                "error_code": error_code,
                "duration": result.execution_duration_ms,
            },
        )
        return result

    def _context(self, command: CapabilityCommand) -> dict:
        return {
            "command_id": command.command_id,
            "tenant_id": command.tenant_id,
            "conversation_id": command.conversation_id,
            "call_session_id": command.call_session_id,
            "capability": command.capability,
            "action": command.action,
        }


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
