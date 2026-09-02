from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

import httpx
import jwt
from contracts import ExecutionSnapshot, RuntimeIntegrationMaterial
from contracts.integration import HttpConnectionConfiguration


class ControlPlaneClient:
    def __init__(self, base_url: str, service_secret: str, audience: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = service_secret
        self._audience = audience
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))

    def _token(self, scopes: list[str]) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {"sub": "backend-core", "service": "backend-core", "aud": self._audience,
             "iat": now, "exp": now + timedelta(seconds=60),
             "scopes": scopes}, self._secret, algorithm="HS256"
        )

    async def materialize_execution_snapshot(self, tenant_id: UUID) -> ExecutionSnapshot:
        response = await self._client.post(
            f"{self._base_url}/internal/v1/execution-snapshots/materialize/tenant/{tenant_id}",
            headers={"Authorization": f"Bearer {self._token(['execution-snapshot:materialize'])}"},
        )
        response.raise_for_status()
        return ExecutionSnapshot.model_validate(response.json())

    async def get_execution_snapshot(self, snapshot_id: UUID) -> ExecutionSnapshot:
        response = await self._client.get(
            f"{self._base_url}/internal/v1/execution-snapshots/{snapshot_id}",
            headers={"Authorization": f"Bearer {self._token(['execution-snapshot:read'])}"},
        )
        response.raise_for_status()
        return ExecutionSnapshot.model_validate(response.json())

    async def integration_execution_material(
        self, tenant_id: UUID, connection_id: UUID
    ) -> RuntimeIntegrationMaterial:
        response = await self._client.post(
            f"{self._base_url}/internal/v1/tenants/{tenant_id}/integration-connections/{connection_id}/execution-material",
            headers={"Authorization": f"Bearer {self._token(['integration-material:read'])}"},
        )
        response.raise_for_status()
        value = response.json()
        config = HttpConnectionConfiguration.model_validate(value["config"])
        host = urlparse(config.endpoint).hostname
        if host is None:
            raise ValueError("integration material endpoint has no host")
        secret = value.get("secret")
        return RuntimeIntegrationMaterial(
            integration_id=UUID(str(value["integration_connection_id"])),
            kind="http",
            provider="http",
            endpoint=config.endpoint,
            static_headers=config.headers,
            authentication_header=(
                config.authentication.header_name
                if config.authentication.type == "api_key_header"
                else None
            ),
            allowed_hosts=[host.lower().rstrip(".")],
            config={},
            secret={"api_key": secret} if isinstance(secret, str) else None,
            connection_revision=int(value["integration_connection_generation"]),
            credential_version=(
                int(value["credential_version_number"])
                if value.get("credential_version_number") is not None
                else None
            ),
        )

    async def handoff_material(
        self, snapshot_id: UUID, destination: str
    ) -> dict[str, object]:
        response = await self._client.post(
            f"{self._base_url}/internal/v1/execution-snapshots/{snapshot_id}/handoff-material",
            headers={"Authorization": f"Bearer {self._token(['handoff-material:read'])}"},
            json={"destination": destination},
        )
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()
