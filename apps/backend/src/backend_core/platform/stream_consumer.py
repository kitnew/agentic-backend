import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

StreamHandler = Callable[[dict[str, str]], Awaitable[None]]


class RedisStreamConsumer:
    def __init__(
        self,
        redis: Redis,
        stream: str,
        group: str,
        consumer: str,
        handler: StreamHandler,
        *,
        max_retries: int = 3,
        stale_idle_ms: int = 30_000,
    ) -> None:
        self._redis = redis
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._handler = handler
        self._max_retries = max_retries
        self._stale_idle_ms = stale_idle_ms
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name=f"stream:{self._group}")

    async def close(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    async def run(self) -> None:
        try:
            await self._redis.xgroup_create(
                self._stream, self._group, id="0", mkstream=True
            )
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
        while True:
            await self.recover_stale()
            messages = cast(
                list[tuple[str, list[tuple[str, dict[str, str]]]]],
                await self._redis.xreadgroup(
                    self._group,
                    self._consumer,
                    {self._stream: ">"},
                    count=10,
                    block=5000,
                ),
            )
            for _, batch in messages:
                for message_id, fields in batch:
                    await self.handle(message_id, fields)

    async def recover_stale(self) -> None:
        claimed = cast(
            tuple[str, list[tuple[str, dict[str, str]]], list[str]],
            await self._redis.xautoclaim(
                self._stream,
                self._group,
                self._consumer,
                min_idle_time=self._stale_idle_ms,
                start_id="0-0",
                count=10,
            ),
        )
        for message_id, fields in claimed[1]:
            await self.handle(message_id, fields)

    async def handle(self, message_id: str, fields: dict[str, str]) -> None:
        try:
            await self._handler(fields)
        except Exception as error:  # noqa: BLE001 - handler failure is retried/DLQ'd
            attempts = await self._redis.incr(
                f"messaging:attempt:{self._stream}:{self._group}:{message_id}"
            )
            if attempts <= self._max_retries:
                return
            await self._redis.xadd(
                f"{self._stream}:{self._group}:dead-letter",
                {
                    "source_message_id": message_id,
                    "error_type": type(error).__name__,
                },
            )
        await self._redis.xack(self._stream, self._group, message_id)
        await self._redis.delete(
            f"messaging:attempt:{self._stream}:{self._group}:{message_id}"
        )
