from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Позже здесь появится запуск database pool,
    # Redis connections и других общих ресурсов.
    yield

    # Здесь будет graceful shutdown.