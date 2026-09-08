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
            print(json.dumps(client.management("GET", path), default=str))
            return
        if action == "show":
            if resource_id is None:
                raise CommandError("resource id is required", 2)
            print(
                json.dumps(
                    client.management("GET", f"{path}/{resource_id}"), default=str
                )
            )
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
            print(
                json.dumps(
                    client.management_mutation(
                        "POST" if action == "create" else "PUT",
                        item_path,
                        etag=etag,
                        json=body,
                    ),
                    default=str,
                )
            )
            return
        if action in {"enable", "disable", "revoke", "rotate"}:
            if resource_id is None:
                raise CommandError("resource id is required", 2)
            body = {"secret": getpass("Secret: ")} if action == "rotate" else {}
            item_path = f"{path}/{resource_id}"
            print(
                json.dumps(
                    client.management_mutation(
                        "POST",
                        f"{item_path}/{action}",
                        etag=client.management_etag(item_path),
                        json=body,
                    ),
                    default=str,
                )
            )
            return
    raise CommandError(f"unsupported {resource} action: {action}", 2)
