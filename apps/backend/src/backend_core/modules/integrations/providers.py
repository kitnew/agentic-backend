from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from backend_core.modules.integrations.models import IntegrationProvider


class IntegrationProviderError(ValueError):
    pass


def validate_config(
    provider: IntegrationProvider,
    config: dict[str, object],
    *,
    allow_empty: bool = False,
) -> None:
    if provider is IntegrationProvider.GOOGLE_SHEETS:
        if config:
            raise IntegrationProviderError("google_sheets config must be empty")
        return
    if allow_empty and not config:
        return
    allowed_hosts = config.get("allowed_hosts")
    header = config.get("api_key_header", "x-api-key")
    if set(config) - {"allowed_hosts", "api_key_header"}:
        raise IntegrationProviderError(
            "managed_webhook config contains unsupported fields"
        )
    if (
        not isinstance(allowed_hosts, list)
        or not allowed_hosts
        or not all(isinstance(host, str) and _hostname(host) for host in allowed_hosts)
    ):
        raise IntegrationProviderError("managed_webhook allowed_hosts must be valid")
    if not isinstance(header, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", header):
        raise IntegrationProviderError("managed_webhook api_key_header is invalid")


def validate_secret(provider: IntegrationProvider, secret: dict[str, object]) -> None:
    try:
        json.dumps(secret, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise IntegrationProviderError("integration secret must be JSON") from error
    if provider is IntegrationProvider.GOOGLE_SHEETS:
        account = secret.get("service_account")
        if set(secret) != {"service_account"} or not isinstance(account, dict):
            raise IntegrationProviderError("google_sheets requires service_account")
        if not all(
            isinstance(account.get(field), str) and account[field]
            for field in ("client_email", "private_key", "token_uri")
        ):
            raise IntegrationProviderError("google_sheets service_account is invalid")
        return
    url = secret.get("url")
    api_key = secret.get("api_key", "")
    parsed = urlparse(url) if isinstance(url, str) else None
    if (
        set(secret) - {"url", "api_key"}
        or not parsed
        or not parsed.scheme
        or not parsed.hostname
    ):
        raise IntegrationProviderError("managed_webhook requires url")
    if not isinstance(api_key, str):
        raise IntegrationProviderError("managed_webhook api_key must be a string")


def _hostname(value: str) -> bool:
    hostname = value.rstrip(".").lower()
    return bool(
        re.fullmatch(
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
            hostname,
        )
    )
