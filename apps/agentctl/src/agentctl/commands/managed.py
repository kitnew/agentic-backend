from __future__ import annotations

import json
from getpass import getpass

from agentctl.commands.errors import CommandError
from agentctl.control_plane import ControlPlaneClient
from agentctl.settings import Settings

RESOURCES = {
    "credential": "credentials",
    "provider": "providers/connections",
    "deployment": "providers/deployments",
}


def _print_response(value: object) -> None:
    if isinstance(value, list):
        value = [
            {
                key: item
                for key, item in resource.items()
                if key not in {"secret", "generation"}
            }
            if isinstance(resource, dict)
            else resource
            for resource in value
        ]
    elif isinstance(value, dict):
        value = {
            key: item
            for key, item in value.items()
            if key not in {"secret", "generation"}
        }
    print(json.dumps(value, default=str))


def run_managed(
    settings: Settings,
    resource: str,
    action: str,
    resource_id: str | None = None,
    payload: str | None = None,
    name: str | None = None,
) -> None:
    path = RESOURCES[resource]
    with ControlPlaneClient(settings) as client:
        if action == "list":
            _print_response(client.management("GET", path))
            return
        if action == "show":
            if resource_id is None:
                raise CommandError("resource id is required", 2)
            _print_response(client.management("GET", f"{path}/{resource_id}"))
            return
        if action in {"create", "configure"}:
            if action == "configure" and resource_id is None:
                raise CommandError("resource id is required", 2)
            if resource == "credential" and action == "create":
                if not name:
                    raise CommandError("--name is required", 2)
                body = {
                    "name": name,
                    "scope": {"type": "platform"},
                    "secret": getpass("Secret: "),
                }
            elif payload is None:
                raise CommandError("--json is required", 2)
            else:
                body = json.loads(payload)
            suffix = "" if action == "create" else f"/{resource_id}"
            item_path = f"{path}{suffix}"
            etag = client.management_etag(item_path) if action == "configure" else None
            _print_response(
                client.management_mutation(
                    "POST" if action == "create" else "PUT",
                    item_path,
                    etag=etag,
                    json=body,
                )
            )
            return
        if action in {"enable", "disable", "revoke", "rotate"}:
            if resource_id is None:
                raise CommandError("resource id is required", 2)
            body = {"secret": getpass("Secret: ")} if action == "rotate" else {}
            item_path = f"{path}/{resource_id}"
            _print_response(
                client.management_mutation(
                    "POST",
                    f"{item_path}/{action}",
                    etag=client.management_etag(item_path),
                    json=body,
                )
            )
            return
    raise CommandError(f"unsupported {resource} action: {action}", 2)
