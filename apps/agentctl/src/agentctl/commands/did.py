from __future__ import annotations

from agentctl.commands.common import _client, _tenant
from agentctl.commands.errors import CommandError
from agentctl.control_plane import ControlPlaneClient
from agentctl.settings import Settings


def run_did(settings: Settings, action: str, tenant_slug: str, phone_number: str | None = None) -> None:
    with _client(settings) as backend:
        tenant = _tenant(backend, tenant_slug)
    with ControlPlaneClient(settings) as client:
        assignments = client.managed(
            "GET", "phone-number-assignments", params={"tenant_id": str(tenant.id)}
        )
        if action == "show":
            for assignment in assignments:
                print(assignment)
            return
        current = next((item for item in assignments if item["enabled"]), None)
        if action == "assign":
            if not phone_number:
                raise CommandError("phone number is required", 2)
            if current is not None:
                client.managed(
                    "POST", f"phone-number-assignments/{current['id']}/disable",
                    json={"expected_generation": current["generation"]},
                )
            print(client.managed(
                "POST", "phone-number-assignments",
                json={"tenant_id": str(tenant.id), "phone_number": phone_number, "enabled": True},
            ))
            return
        if action == "remove":
            if current is None:
                print("No enabled DID assignment.")
                return
            print(client.managed(
                "POST", f"phone-number-assignments/{current['id']}/disable",
                json={"expected_generation": current["generation"]},
            ))
            return
    raise CommandError(f"unsupported DID action: {action}", 2)
