import asyncio
import os
import re
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
from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url

BACKEND_ROOT = Path(__file__).parents[2]
REPOSITORY_ROOT = Path(__file__).parents[4]
TEST_DATABASE_PATTERN = re.compile(r"agentic_backend_test_[0-9a-f]{32}")
ADMIN_TOKEN = "test-admin-token-with-at-least-32-characters"
VOICE_AGENT_SECRET = "test-voice-agent-secret-with-at-least-32-characters"
JOB_WORKER_SECRET = "test-job-worker-secret-with-at-least-32-characters"
BACKEND_CORE_SERVICE_SECRET = (
    "test-backend-core-service-secret-with-at-least-32-characters"
)


def dsn(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def test_database_server() -> tuple[URL, set[str]]:
    raw_admin_url = os.getenv("TEST_DATABASE_ADMIN_URL")
    if raw_admin_url:
        admin_url = make_url(raw_admin_url)
    else:
        development = dotenv_values(REPOSITORY_ROOT / "infrastructure/compose/.env.dev")
        password = development.get("POSTGRES_PASSWORD")
        if not password:
            pytest.skip("development PostgreSQL credentials are unavailable")
        admin_url = URL.create(
            "postgresql+asyncpg",
            username="postgres",
            password=password,
            host="127.0.0.1",
            port=int(development.get("POSTGRES_PORT") or 5432),
            database="postgres",
        )
    application_databases = {"backend"}
    if configured_url := os.getenv("DATABASE_URL"):
        application_databases.add(make_url(configured_url).database or "")
    application_databases.add(admin_url.database or "")
    return admin_url, application_databases


def assert_safe_test_database(
    admin_url: URL,
    application_databases: set[str],
    database_name: str,
) -> None:
    if (
        TEST_DATABASE_PATTERN.fullmatch(database_name) is None
        or database_name in application_databases
        or database_name in {"postgres", "template0", "template1"}
        or not admin_url.host
    ):
        raise RuntimeError(f"refusing unsafe test database target: {database_name}")


async def upgrade_database(database_url: str, revision: str) -> None:
    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    await asyncio.to_thread(command.upgrade, alembic, revision)


@pytest.fixture
def migrate_database():
    return upgrade_database


@pytest_asyncio.fixture
async def isolated_database_url() -> AsyncIterator[str]:
    admin_url, application_databases = test_database_server()
    database_name = f"agentic_backend_test_{uuid4().hex}"
    assert_safe_test_database(admin_url, application_databases, database_name)
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
        assert_safe_test_database(admin_url, application_databases, database_name)
        await admin_connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin_connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin_connection.close()


@pytest_asyncio.fixture
async def migrated_database_url(
    isolated_database_url: str,
) -> AsyncIterator[str]:
    await upgrade_database(isolated_database_url, "head")
    # The component cutover is intentionally destructive; isolated databases
    # are dropped by the outer fixture instead of exercising a fake downgrade.
    yield isolated_database_url


@pytest.fixture
def app_settings(migrated_database_url: str) -> Settings:
    return Settings.model_validate(
        {
            "database_url": migrated_database_url,
            "admin_api_token": ADMIN_TOKEN,
            "internal_api_audience": "backend-core",
            "backend_core_service_secret": BACKEND_CORE_SERVICE_SECRET,
            "control_plane_url": "http://control-plane-service:8000",
            "voice_agent_service_secret": VOICE_AGENT_SECRET,
            "job_worker_service_secret": JOB_WORKER_SECRET,
            "integration_encryption_key": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
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
