import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import jwt
from contracts import (
    AppendConversationMessage,
    CapabilityInvocationRequest,
    CapabilityInvocationResponse,
    CapabilityInvocationStatus,
    ConversationMessageResponse,
    VoiceAgentRuntimeContext,
)

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

    async def append_conversation_message(
        self,
        call_id: UUID,
        data: AppendConversationMessage,
    ) -> ConversationMessageResponse:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client.request(
                    "POST",
                    f"/internal/v1/calls/{call_id}/messages",
                    headers={
                        "Authorization": (
                            "Bearer "
                            f"{self.service_token('conversation-message:append')}"
                        )
                    },
                    json=data.model_dump(mode="json"),
                    timeout=2.0,
                )
                if response.status_code >= 500:
                    last_error = httpx.HTTPStatusError(
                        "conversation append server error",
                        request=response.request,
                        response=response,
                    )
                    if attempt < 2:
                        continue
                    raise last_error
                response.raise_for_status()
                return ConversationMessageResponse.model_validate(response.json())
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
                if attempt == 2:
                    raise
        assert last_error is not None
        raise last_error

    async def runtime_context(self, call_id: UUID) -> VoiceAgentRuntimeContext:
        response = await self.request(
            "GET",
            f"/internal/v1/calls/{call_id}/runtime-context",
            "call-session:runtime-context:read",
        )
        return VoiceAgentRuntimeContext.model_validate(response.json())

    async def invoke_capability(
        self,
        call_id: UUID,
        request: CapabilityInvocationRequest,
    ) -> CapabilityInvocationResponse:
        response = await self.request(
            "POST",
            f"/internal/v1/calls/{call_id}/capability-invocations",
            "capability-invocation:create",
            json=request.model_dump(mode="json"),
        )
        return CapabilityInvocationResponse.model_validate(response.json())

    async def capability_invocation(
        self,
        call_id: UUID,
        invocation_id: UUID,
    ) -> CapabilityInvocationResponse:
        response = await self.request(
            "GET",
            f"/internal/v1/calls/{call_id}/capability-invocations/{invocation_id}",
            "capability-invocation:read",
        )
        return CapabilityInvocationResponse.model_validate(response.json())

    async def wait_for_capability(
        self,
        call_id: UUID,
        invocation: CapabilityInvocationResponse,
    ) -> CapabilityInvocationResponse:
        terminal = {
            CapabilityInvocationStatus.SUCCEEDED,
            CapabilityInvocationStatus.FAILED,
            CapabilityInvocationStatus.EXPIRED,
        }
        deadline = (
            asyncio.get_running_loop().time()
            + self._settings.capability_poll_timeout_seconds
        )
        while invocation.status not in terminal:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("capability invocation did not complete in time")
            await asyncio.sleep(
                min(self._settings.capability_poll_interval_seconds, remaining)
            )
            invocation = await self.capability_invocation(call_id, invocation.id)
        return invocation

    async def activate(self, call_id: UUID) -> None:
        await self.request(
            "POST",
            f"/internal/v1/call-sessions/{call_id}/activate",
            "call-session:activate",
        )

    async def complete(self, call_id: UUID, conversation_status: str) -> None:
        await self.request(
            "POST",
            f"/internal/v1/call-sessions/{call_id}/complete",
            "call-session:complete",
            json={"conversation_status": conversation_status},
        )

    async def fail(
        self,
        call_id: UUID,
        reason: str,
        conversation_status: str,
    ) -> None:
        await self.request(
            "POST",
            f"/internal/v1/call-sessions/{call_id}/fail",
            "call-session:fail",
            json={
                "failure_reason": reason,
                "conversation_status": conversation_status,
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()


class CallFinalizer:
    def __init__(self, backend: BackendClient, call_id: UUID) -> None:
        self._backend = backend
        self._call_id = call_id
        self._done = False
        self._lock = asyncio.Lock()

    async def complete(self, conversation_status: str) -> None:
        async with self._lock:
            if self._done:
                return
            await self._backend.complete(self._call_id, conversation_status)
            self._done = True

    async def fail(self, reason: str, conversation_status: str) -> None:
        async with self._lock:
            if self._done:
                return
            await self._backend.fail(self._call_id, reason, conversation_status)
            self._done = True
