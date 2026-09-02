from __future__ import annotations

from getpass import getpass
from typing import Any

from agentctl.commands.common import _client, _tenant
from agentctl.commands.errors import CommandError
from agentctl.control_plane import ControlPlaneClient
from agentctl.settings import Settings


def _secret(api_key: str | None) -> str:
    value = api_key or getpass("API key: ")
    if not value:
        raise CommandError("API key is required", 2)
    return value


def _config(endpoint: str | None, auth: str, auth_header: str, headers: list[str], allowed_hosts: list[str]) -> dict[str, Any]:
    if not endpoint:
        raise CommandError("--endpoint is required", 2)
    values = {}
    for item in headers:
        name, separator, value = item.partition("=")
        if not separator or not name.strip():
            raise CommandError("header must use NAME=VALUE syntax", 2)
        values[name.strip()] = value
    return {
        "endpoint": endpoint,
        "authentication": {"type": "none" if auth == "none" else "api_key_header", "header_name": auth_header},
        "headers": values,
        "security": {"additional_allowed_hosts": allowed_hosts},
    }


def run_integration(settings: Settings, action: str, tenant_slug: str, key: str | None = None, *, kind: str = "http", endpoint: str | None = None, auth: str = "none", auth_header: str = "X-API-Key", headers: list[str] | None = None, additional_allowed_hosts: list[str] | None = None, api_key: str | None = None) -> None:
    if kind != "http":
        raise CommandError("only HTTP integrations are supported", 2)
    with _client(settings) as backend:
        tenant = _tenant(backend, tenant_slug)
    with ControlPlaneClient(settings) as client:
        items = client.managed("GET", "integration-connections", params={"tenant_id": str(tenant.id)})
        if action == "list":
            for item in items:
                print(f"{item['key']}\thttp\t{item['enabled']}")
            return
        if not key:
            raise CommandError("integration key is required", 2)
        current = next((item for item in items if item["key"] == key), None)
        if action == "create":
            credential_ref = None
            if auth != "none":
                credential_ref = client.managed("POST", "credentials", json={"name": f"integration:{tenant.id}:{key}", "secret": _secret(api_key)})["id"]
            print(client.managed("POST", "integration-connections", json={"tenant_id": str(tenant.id), "key": key, "integration_kind": "http", "config": _config(endpoint, auth, auth_header, headers or [], additional_allowed_hosts or []), "credential_ref": credential_ref}))
            return
        if current is None:
            raise CommandError(f"unknown integration connection: {key}", 2)
        if action == "show":
            print(current)
            return
        if action == "configure":
            print(client.managed("PUT", f"integration-connections/{current['id']}", json={"config": _config(endpoint, auth, auth_header, headers or [], additional_allowed_hosts or []), "expected_generation": current["generation"]}))
            return
        if action in {"enable", "disable"}:
            print(client.managed("POST", f"integration-connections/{current['id']}/{action}", json={"expected_generation": current["generation"]}))
            return
        if action in {"rotate-credential", "revoke-credential"}:
            credential = current.get("credential_ref")
            if not credential:
                raise CommandError("integration has no credential", 2)
            operation = "rotate" if action.startswith("rotate") else "revoke"
            body = {"secret": _secret(api_key)} if operation == "rotate" else {}
            print(client.managed("POST", f"credentials/{credential}/{operation}", json=body))
            return
        if action == "delete":
            raise CommandError("hard deletion is not supported; use disable", 2)
        if action == "validate":
            print(client.managed("POST", f"integration-connections/{current['id']}/validate"))
            return
    raise CommandError(f"unsupported integration action: {action}", 2)
