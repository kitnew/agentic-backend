import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await app.state.livekit.start()
    logger.info("Backend Core started")

    try:
        yield
    finally:
        await app.state.livekit.aclose()
        await app.state.database.close()
        logger.info("Backend Core stopped")
