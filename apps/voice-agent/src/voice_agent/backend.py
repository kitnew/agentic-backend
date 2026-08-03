import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import jwt
from contracts import VoiceAgentRuntimeContext

from voice_agent.settings import VoiceAgentSettings


class BackendClient:
    def __init__(self, settings: VoiceAgentSettings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.backend_core_url.rstrip("/"),
            timeout=settings.backend_http_timeout_seconds,
        )

    def service_token(self, scope: str) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": "voice-agent:livekit-worker",
                "service": "voice-agent",
                "aud": self._settings.internal_api_audience,
                "iat": now,
                "exp": now + timedelta(seconds=60),
                "scopes": [scope],
            },
            self._settings.voice_agent_service_secret.get_secret_value(),
            algorithm="HS256",
        )

    async def request(
        self,
        method: str,
        path: str,
        scope: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        response = await self._client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {self.service_token(scope)}"},
            json=json,
        )
        response.raise_for_status()
        return response

    async def runtime_context(self, call_id: UUID) -> VoiceAgentRuntimeContext:
        response = await self.request(
            "GET",
            f"/internal/v1/calls/{call_id}/runtime-context",
            "call-session:runtime-context:read",
        )
        return VoiceAgentRuntimeContext.model_validate(response.json())

    async def activate(self, call_id: UUID) -> None:
        await self.request(
            "POST",
            f"/internal/v1/call-sessions/{call_id}/activate",
            "call-session:activate",
        )

    async def complete(self, call_id: UUID) -> None:
        await self.request(
            "POST",
            f"/internal/v1/call-sessions/{call_id}/complete",
            "call-session:complete",
        )

    async def fail(self, call_id: UUID, reason: str) -> None:
        await self.request(
            "POST",
            f"/internal/v1/call-sessions/{call_id}/fail",
            "call-session:fail",
            json={"failure_reason": reason},
        )

    async def aclose(self) -> None:
        await self._client.aclose()


class CallFinalizer:
    def __init__(self, backend: BackendClient, call_id: UUID) -> None:
        self._backend = backend
        self._call_id = call_id
        self._done = False
        self._lock = asyncio.Lock()

    async def complete(self) -> None:
        async with self._lock:
            if self._done:
                return
            await self._backend.complete(self._call_id)
            self._done = True

    async def fail(self, reason: str) -> None:
        async with self._lock:
            if self._done:
                return
            await self._backend.fail(self._call_id, reason)
            self._done = True
