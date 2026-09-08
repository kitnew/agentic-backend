from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import jwt
from contracts import (
    BackendExecutionContext,
    HandoffExecutionMaterial,
    InboundRoute,
    IntegrationExecutionMaterial,
    VoiceExecutionContext,
    WorkerExecutionContext,
)


class ControlPlaneClient:
    def __init__(self, base_url: str, service_secret: str, audience: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = service_secret
        self._audience = audience
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))

    def _token(self, scope: str) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": "backend-core",
                "service": "backend-core",
                "aud": self._audience,
                "iat": now,
                "exp": now + timedelta(seconds=60),
                "scopes": [scope],
            },
            self._secret,
            algorithm="HS256",
        )

    async def _request(
        self,
        method: str,
        path: str,
        scope: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        response = await self._client.request(
            method,
            f"{self._base_url}{path}",
            params=params,
            json=json,
            headers={
                "Authorization": f"Bearer {self._token(scope)}",
                **(headers or {}),
            },
        )
        response.raise_for_status()
        return response

    async def create_execution(
        self,
        tenant_id: UUID,
        *,
        idempotency_key: str,
        context: dict[str, object] | None = None,
    ) -> BackendExecutionContext:
        response = await self._request(
            "POST",
            "/internal/v1/executions",
            "execution:create",
            json={"tenant_id": str(tenant_id), "context": context},
            headers={"Idempotency-Key": idempotency_key},
        )
        return BackendExecutionContext.model_validate(response.json())

    async def voice_context(self, execution_id: UUID) -> VoiceExecutionContext:
        response = await self._request(
            "GET",
            f"/internal/v1/executions/{execution_id}/voice-context",
            "execution:voice-context:read",
        )
        return VoiceExecutionContext.model_validate(response.json())

    async def worker_context(
        self, execution_id: UUID, action_key: str
    ) -> WorkerExecutionContext:
        response = await self._request(
            "GET",
            f"/internal/v1/executions/{execution_id}/worker-context",
            "execution:worker-context:read",
            params={"action_key": action_key},
        )
        return WorkerExecutionContext.model_validate(response.json())

    async def resolve_phone_number(self, phone_number: str) -> InboundRoute:
        response = await self._request(
            "GET",
            "/internal/v1/telephony/inbound-route",
            "telephony:resolve",
            params={"phone_number": phone_number},
        )
        return InboundRoute.model_validate(response.json())

    async def integration_execution_material(
        self, execution_id: UUID, integration_key: str
    ) -> IntegrationExecutionMaterial:
        response = await self._request(
            "POST",
            f"/internal/v1/executions/{execution_id}/integrations/{integration_key}/material",
            "integration-material:read",
        )
        return IntegrationExecutionMaterial.model_validate(response.json())

    async def handoff_material(
        self, execution_id: UUID, destination_key: str
    ) -> HandoffExecutionMaterial:
        response = await self._request(
            "POST",
            f"/internal/v1/executions/{execution_id}/handoff/{destination_key}/material",
            "handoff-material:read",
        )
        return HandoffExecutionMaterial.model_validate(response.json())

    async def aclose(self) -> None:
        await self._client.aclose()
