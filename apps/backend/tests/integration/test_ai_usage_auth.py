"""Exercise the Voice Agent client against Backend's real internal auth dependency."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from backend_core.modules.calls import router as calls_router
from contracts import CallModelUsage, CallUsageReport
from fastapi import FastAPI
from pydantic import SecretStr
from voice_agent.backend import BackendClient
from voice_agent.settings import VoiceAgentSettings


@pytest.mark.asyncio
async def test_voice_client_ai_usage_requires_valid_internal_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "voice-agent-test-secret-at-least-32-characters"
    settings = VoiceAgentSettings.model_validate(
        {
            "livekit_url": "ws://livekit:7880",
            "livekit_api_key": "test-key",
            "livekit_api_secret": "test-secret",
            "livekit_agent_name": "test-agent",
            "backend_core_url": "http://backend.test",
            "voice_agent_service_secret": secret,
            "internal_api_audience": "backend-core",
        }
    )
    accepted = []

    async def upsert(_session, call_id, report, _prices):
        accepted.append((call_id, report))
        return True, []

    @asynccontextmanager
    async def transaction():
        yield object()

    monkeypatch.setattr(calls_router, "upsert_call_usage", upsert)
    app = FastAPI()
    app.include_router(calls_router.runtime_router)
    app.state.settings = SimpleNamespace(
        voice_agent_service_secret=SecretStr(secret),
        job_worker_service_secret=SecretStr("job-worker-test-secret-at-least-32-characters"),
        internal_api_audience="backend-core",
        ai_usage_prices={},
    )
    app.state.database = SimpleNamespace(transaction=transaction)
    app.state.core_metrics = None

    client = BackendClient(settings)
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://backend.test"
    )
    call_id = uuid4()
    path = f"/internal/v1/calls/{call_id}/ai-usage"
    report = CallUsageReport(
        usage=[
            CallModelUsage(
                provider="openai",
                service="llm",
                model="test-model",
                observed_at=datetime.now(UTC),
                counters={"input_tokens": 1},
            )
        ]
    )
    try:
        assert (await client._client.put(path, json=report.model_dump(mode="json"))).status_code == 401
        assert (
            await client._client.put(
                path,
                json=report.model_dump(mode="json"),
                headers={"Authorization": "Bearer invalid"},
            )
        ).status_code == 401
        await client.report_ai_usage(call_id, report)
        assert accepted == [(call_id, report)]
    finally:
        await client.aclose()
