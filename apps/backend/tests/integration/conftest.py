import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import jwt
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from backend_core.bootstrap.settings import Settings
from sqlalchemy.engine import URL, make_url

BACKEND_ROOT = Path(__file__).parents[2]
ADMIN_TOKEN = "test-admin-token-with-at-least-32-characters"
VOICE_AGENT_SECRET = "test-voice-agent-secret-with-at-least-32-characters"
JOB_WORKER_SECRET = "test-job-worker-secret-with-at-least-32-characters"


def dsn(url: URL) -> str:
    return url.render_as_string(hide_password=False)


@pytest_asyncio.fixture(scope="session")
async def isolated_database_url() -> AsyncIterator[str]:
    raw_admin_url = os.getenv("TEST_DATABASE_ADMIN_URL")
    if not raw_admin_url:
        pytest.skip("set TEST_DATABASE_ADMIN_URL to run PostgreSQL integration tests")

    admin_url = make_url(raw_admin_url)
    database_name = f"backend_test_{uuid4().hex}"
    admin_connection = await asyncpg.connect(
        dsn(admin_url.set(drivername="postgresql"))
    )

    try:
        await admin_connection.execute(f'CREATE DATABASE "{database_name}"')
        yield dsn(
            admin_url.set(
                drivername="postgresql+asyncpg",
                database=database_name,
            )
        )
    finally:
        await admin_connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin_connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin_connection.close()


@pytest_asyncio.fixture(scope="session")
async def migrated_database_url(
    isolated_database_url: str,
) -> AsyncIterator[str]:
    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option(
        "sqlalchemy.url",
        isolated_database_url.replace("%", "%%"),
    )
    await asyncio.to_thread(command.upgrade, alembic, "head")
    try:
        yield isolated_database_url
    finally:
        await asyncio.to_thread(command.downgrade, alembic, "base")


@pytest.fixture
def app_settings(migrated_database_url: str) -> Settings:
    return Settings.model_validate(
        {
            "database_url": migrated_database_url,
            "admin_api_token": ADMIN_TOKEN,
            "internal_api_audience": "backend-core",
            "voice_agent_service_secret": VOICE_AGENT_SECRET,
            "job_worker_service_secret": JOB_WORKER_SECRET,
            "livekit_url": "ws://livekit:7880",
            "livekit_public_url": "ws://localhost:7880",
            "livekit_api_key": "test-key",
            "livekit_api_secret": "test-livekit-secret-with-at-least-32-characters",
            "livekit_agent_name": "hospitality-voice-agent",
            "livekit_participant_token_ttl_seconds": 600,
        }
    )


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture
def service_token():
    def issue(
        *,
        service: str,
        scopes: list[str],
        secret: str,
        audience: str = "backend-core",
        issued_at: datetime | None = None,
        expires_at: datetime | None = None,
        subject: str | None = None,
    ) -> str:
        now = issued_at or datetime.now(UTC)
        claims: dict[str, Any] = {
            "sub": subject or f"{service}:test-instance",
            "service": service,
            "aud": audience,
            "iat": now,
            "exp": expires_at or now + timedelta(minutes=5),
            "scopes": scopes,
        }
        return jwt.encode(claims, secret, algorithm="HS256")

    return issue
