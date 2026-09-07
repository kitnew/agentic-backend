import httpx

from control_plane.application.providers import ProviderValidationResult
from control_plane.domain.managed_resources import DeploymentKind


class HttpProviderValidator:
    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self._timeout = httpx.Timeout(timeout_seconds)

    async def validate_connection(
        self,
        provider_kind: str,
        connection_config: dict[str, object],
        secret: str,
    ) -> ProviderValidationResult:
        url, headers, params = self._request(
            provider_kind, connection_config, secret
        )
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False
            ) as client:
                response = await client.get(url, headers=headers, params=params)
        except httpx.HTTPError as error:
            return ProviderValidationResult(
                True, False, "provider_unavailable", type(error).__name__
            )
        if response.is_success:
            return ProviderValidationResult(True, True)
        return ProviderValidationResult(
            True, False, "provider_rejected", f"provider returned HTTP {response.status_code}"
        )

    async def validate_deployment(
        self,
        provider_kind: str,
        connection_config: dict[str, object],
        _deployment_kind: DeploymentKind,
        _deployment_config: dict[str, object],
        secret: str,
    ) -> ProviderValidationResult:
        return await self.validate_connection(
            provider_kind, connection_config, secret
        )

    @staticmethod
    def _request(
        provider_kind: str,
        connection_config: dict[str, object],
        secret: str,
    ) -> tuple[str, dict[str, str], dict[str, str]]:
        if provider_kind == "azure_openai":
            endpoint = str(connection_config["endpoint"]).rstrip("/")
            params = (
                {"api-version": str(connection_config["api_version"])}
                if connection_config.get("api_version")
                else {}
            )
            return f"{endpoint}/openai/models", {"api-key": secret}, params
        if provider_kind == "elevenlabs":
            return (
                "https://api.elevenlabs.io/v1/models",
                {"xi-api-key": secret},
                {},
            )
        if provider_kind == "deepgram":
            return (
                "https://api.deepgram.com/v1/projects",
                {"Authorization": f"Token {secret}"},
                {},
            )
        raise ValueError("unsupported provider kind")
