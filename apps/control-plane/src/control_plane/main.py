import sys
from argparse import ArgumentParser
from collections.abc import Sequence
from json import dumps, loads

import httpx

from control_plane import __version__
from control_plane.commands.tenants import fetch_tenants
from control_plane.settings import Settings, SettingsError


def parser() -> ArgumentParser:
    root = ArgumentParser(prog="agentctl")
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root.add_argument("--api-url", help="override AGENTCTL_API_URL")
    resources = root.add_subparsers(dest="resource", required=True)
    tenant = resources.add_parser("tenant", help="inspect tenants")
    tenant.add_subparsers(dest="action", required=True).add_parser(
        "list", help="list tenants"
    )
    return root


def response_detail(content: bytes) -> str:
    try:
        payload = loads(content)
        detail = (
            payload.get("detail", payload) if isinstance(payload, dict) else payload
        )
        text = detail if isinstance(detail, str) else dumps(detail, ensure_ascii=False)
    except UnicodeDecodeError, ValueError:
        text = content.decode(errors="replace")
    return text.strip()[:500] or "empty response"


def fail(message: str, code: int) -> int:
    print(f"agentctl: {message}", file=sys.stderr)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        settings = Settings.load(arguments.api_url)
        response = fetch_tenants(settings)
    except SettingsError as error:
        return fail(f"configuration error: {error}", 2)
    except httpx.TransportError as error:
        return fail(f"connection failed: {error}", 3)
    except Exception as error:  # noqa: BLE001 - CLI boundary hides expected tracebacks
        return fail(f"unexpected client failure: {error}", 1)

    if response.status_code in {401, 403}:
        return fail(
            f"authentication/authorization failed ({response.status_code})",
            4,
        )
    if response.status_code >= 400:
        return fail(
            f"Backend API error ({response.status_code}): "
            f"{response_detail(response.content)}",
            5,
        )
    if not isinstance(response.parsed, list):
        return fail("unexpected client failure: invalid Backend response", 1)

    if not response.parsed:
        print("No tenants.")
    for tenant in response.parsed:
        print(f"{tenant.slug}\t{tenant.id}\t{tenant.status.value}")
    return 0
