from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class Database:
    def __init__(self, url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self._connected = False

    async def connect(self) -> None:
        await self.ping()
        self._connected = True

    async def ping(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    @property
    def ready(self) -> bool:
        return self._connected

    @property
    def instrumentable_engine(self) -> Engine:
        return self._engine.sync_engine

    async def close(self) -> None:
        self._connected = False
        await self._engine.dispose()
