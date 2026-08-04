import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from backend_core.platform.outbox import OutboxDispatcher

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await app.state.livekit.start()
    redis: Redis | None = None
    dispatcher: OutboxDispatcher | None = None
    if app.state.settings.outbox_dispatch_enabled:
        redis = Redis.from_url(str(app.state.settings.redis_url), decode_responses=True)
        dispatcher = OutboxDispatcher(
            app.state.database,
            redis,
            app.state.settings.capability_job_stream,
            app.state.settings.outbox_dispatch_interval_seconds,
        )
        dispatcher.start()
    logger.info("Backend Core started")

    try:
        yield
    finally:
        if dispatcher is not None:
            await dispatcher.close()
        if redis is not None:
            await redis.aclose()
        await app.state.livekit.aclose()
        await app.state.database.close()
        logger.info("Backend Core stopped")
