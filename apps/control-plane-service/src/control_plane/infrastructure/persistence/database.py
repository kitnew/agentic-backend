from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

CONTROL_PLANE_SCHEMA_REVISION = "0001_versioned_components"
CONTROL_PLANE_VERSION_TABLE = "control_plane_alembic_version"


class Database:
    def __init__(self, url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self._engine, expire_on_commit=False)
        self._connected = False

    async def connect(self) -> None:
        await self.ping()
        self._connected = True

    async def ping(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def schema_compatible(self) -> bool:
        try:
            async with self._engine.connect() as connection:
                revision = await connection.scalar(
                    text(f"SELECT version_num FROM {CONTROL_PLANE_VERSION_TABLE}")
                )
        except Exception:  # noqa: BLE001
            return False
        return revision == CONTROL_PLANE_SCHEMA_REVISION

    @property
    def ready(self) -> bool:
        return self._connected

    @property
    def instrumentable_engine(self) -> Engine:
        return self._engine.sync_engine

    async def close(self) -> None:
        self._connected = False
        await self._engine.dispose()
