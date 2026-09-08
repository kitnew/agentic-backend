from __future__ import annotations

from agentctl.commands.common import _client, _tenant
from agentctl.commands.errors import CommandError
from agentctl.control_plane import ControlPlaneClient
from agentctl.settings import Settings


def run_did(
    settings: Settings, action: str, tenant_slug: str, phone_number: str | None = None
) -> None:
    with _client(settings) as backend:
        tenant = _tenant(backend, tenant_slug)
    with ControlPlaneClient(settings) as client:
        path = f"tenants/{tenant.id}/telephony/phone-number-assignments"
        assignments = client.management("GET", path)
        if action == "show":
            for assignment in assignments:
                print(assignment)
            return
        current = next((item for item in assignments if item["enabled"]), None)
        if action == "assign":
            if not phone_number:
                raise CommandError("phone number is required", 2)
            if current is not None:
                etag = client.management_etag(f"{path}/{current['id']}")
                client.management_mutation(
                    "POST", f"{path}/{current['id']}/disable", etag=etag
                )
            print(
                client.management_mutation(
                    "POST", path, json={"phone_number": phone_number}
                )
            )
            return
        if action == "remove":
            if current is None:
                print("No enabled DID assignment.")
                return
            etag = client.management_etag(f"{path}/{current['id']}")
            print(
                client.management_mutation(
                    "POST", f"{path}/{current['id']}/disable", etag=etag
                )
            )
            return
    raise CommandError(f"unsupported DID action: {action}", 2)
