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

    async def schema_compatible(self) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_bootstrap_starts_without_nats_or_outbox_dependencies() -> None:
    database = Database()
    app = create_app(
        Settings(
            database_url=PostgresDsn(
                "postgresql+asyncpg://user:pass@localhost:5432/db"
            ),
            control_plane_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            voice_agent_service_secret="voice-agent-test-secret",
            job_worker_service_secret="job-worker-test-secret",
            backend_core_service_secret="backend-core-test-secret",
        ),
        database,  # type: ignore[arg-type]
    )

    async with app.router.lifespan_context(app):
        readiness = await app.state.lifecycle.readiness()
        assert readiness.ready

    assert database.closed
    assert not hasattr(app.state, "nats")
    assert not hasattr(app.state, "outbox_relay")
