import pytest
from control_plane.bootstrap import create_app
from control_plane.settings import Settings
from pydantic import PostgresDsn


class Database:
    def __init__(self) -> None:
        self.closed = False

    async def connect(self) -> None:
        pass

    async def ping(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True


class Nats:
    def __init__(self) -> None:
        self.drained = False
        self.closed = False

    async def connect(self) -> None:
        pass

    async def ping(self) -> None:
        pass

    async def drain(self) -> None:
        self.drained = True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_bootstrap_wires_lifespan_with_supplied_dependencies() -> None:
    database = Database()
    nats = Nats()
    app = create_app(
        Settings(
            database_url=PostgresDsn("postgresql+asyncpg://user:pass@localhost:5432/db")
        ),
        database,  # type: ignore[arg-type]
        nats,  # type: ignore[arg-type]
    )

    async with app.router.lifespan_context(app):
        readiness = await app.state.lifecycle.readiness()
        assert readiness.ready

    assert database.closed
    assert nats.drained
    assert nats.closed
