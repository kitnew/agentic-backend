from __future__ import annotations

import json
import re

from contracts.integration import HttpConnectionConfiguration

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
    if provider.value == "http":
        if allow_empty and not config:
            return
        try:
            HttpConnectionConfiguration.model_validate(config)
        except ValueError as error:
            raise IntegrationProviderError("integration_configuration_invalid") from error
        return
    raise IntegrationProviderError("unsupported integration kind")


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
    if provider.value == "http":
        if set(secret) != {"api_key"} or not isinstance(secret["api_key"], str) or not secret["api_key"]:
            raise IntegrationProviderError("http requires api_key")
        return
    raise IntegrationProviderError("unsupported integration kind")


def _hostname(value: str) -> bool:
    hostname = value.rstrip(".").lower()
    return bool(
        re.fullmatch(
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
            hostname,
        )
    )
